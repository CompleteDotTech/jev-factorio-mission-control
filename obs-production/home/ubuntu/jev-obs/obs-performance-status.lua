-- Read-only OBS telemetry. No scene, encoder, service, or output settings are read.
-- Counters match OBS 32.2's Stats window; compare deltas within one OBS run.
local obs = obslua
local destination = ""
local media_api = nil
local sequence = 0

local function initialize_media_api()
    -- The media-io functions are not exported by the installed Lua wrapper.
    -- LuaJIT FFI calls the same public libobs ABI used by OBS's Stats window.
    local ok, api = pcall(function()
        local ffi = require("ffi")
        ffi.cdef[[
            void *obs_get_video(void);
            uint32_t video_output_get_total_frames(const void *video);
            uint32_t video_output_get_skipped_frames(const void *video);
        ]]
        -- Resolve the already-loaded OBS library, rather than opening another
        -- version by soname. Touch each symbol here so absence fails closed.
        local lib = ffi.C
        local get_video = lib.obs_get_video
        local get_total = lib.video_output_get_total_frames
        local get_skipped = lib.video_output_get_skipped_frames
        return {ffi = ffi, lib = lib}
    end)
    if ok then media_api = api end
end

local function output_stats(d, prefix, output)
    obs.obs_data_set_bool(d, prefix .. "_present", output ~= nil)
    if output == nil then return end
    local output_id = obs.obs_output_get_id(output)
    obs.obs_data_set_string(d, prefix .. "_output_id", output_id)
    local encoder = obs.obs_output_get_video_encoder(output)
    if encoder ~= nil then
        -- Borrowed encoder reference remains owned by the output.
        obs.obs_data_set_string(d, prefix .. "_video_encoder_id", obs.obs_encoder_get_id(encoder))
        obs.obs_data_set_string(d, prefix .. "_video_encoder_name", obs.obs_encoder_get_name(encoder))
    end
    obs.obs_data_set_bool(d, prefix .. "_active", obs.obs_output_active(output))
    obs.obs_data_set_bool(d, prefix .. "_reconnecting", obs.obs_output_reconnecting(output))
    obs.obs_data_set_int(d, prefix .. "_total_frames", obs.obs_output_get_total_frames(output))
    if prefix == "stream" then
        -- OBS 32.2 MPEG-TS/SRT omits dropped-frame and congestion callbacks;
        -- libobs returns zero for absent callbacks, not measured zero loss.
        obs.obs_data_set_bool(d, prefix .. "_network_counters_available", output_id == "rtmp_output")
        obs.obs_data_set_int(d, prefix .. "_network_dropped_frames", obs.obs_output_get_frames_dropped(output))
    end
    obs.obs_data_set_int(d, prefix .. "_total_bytes", obs.obs_output_get_total_bytes(output))
    obs.obs_data_set_double(d, prefix .. "_congestion", obs.obs_output_get_congestion(output))
    obs.obs_data_set_int(d, prefix .. "_width", obs.obs_output_get_width(output))
    obs.obs_data_set_int(d, prefix .. "_height", obs.obs_output_get_height(output))
    obs.obs_output_release(output)
end

local function sample()
    if destination == "" then return end
    sequence = sequence + 1
    local d = obs.obs_data_create()
    obs.obs_data_set_int(d, "schema_version", 1)
    obs.obs_data_set_int(d, "sequence", sequence)
    obs.obs_data_set_int(d, "updated_epoch", os.time())
    obs.obs_data_set_int(d, "monotonic_ns", obs.os_gettime_ns())
    obs.obs_data_set_double(d, "active_fps", obs.obs_get_active_fps())
    obs.obs_data_set_double(d, "average_render_ms", obs.obs_get_average_frame_time_ns() / 1000000)
    obs.obs_data_set_int(d, "render_total_frames", obs.obs_get_total_frames())
    obs.obs_data_set_int(d, "render_lagged_frames", obs.obs_get_lagged_frames())

    local video = obs.obs_video_info()
    if obs.obs_get_video_info(video) then
        obs.obs_data_set_int(d, "configured_fps_num", video.fps_num)
        obs.obs_data_set_int(d, "configured_fps_den", video.fps_den)
        obs.obs_data_set_int(d, "base_width", video.base_width)
        obs.obs_data_set_int(d, "base_height", video.base_height)
        obs.obs_data_set_int(d, "output_width", video.output_width)
        obs.obs_data_set_int(d, "output_height", video.output_height)
    end

    local have_media = false
    if media_api ~= nil then
        local ok = pcall(function()
            local handle = media_api.lib.obs_get_video()
            if handle == media_api.ffi.NULL then return end
            obs.obs_data_set_int(d, "video_output_total_frames", tonumber(media_api.lib.video_output_get_total_frames(handle)))
            obs.obs_data_set_int(d, "video_output_skipped_frames", tonumber(media_api.lib.video_output_get_skipped_frames(handle)))
            have_media = true
        end)
        if not ok then media_api = nil end
    end
    obs.obs_data_set_bool(d, "video_output_counters_available", have_media)
    output_stats(d, "stream", obs.obs_frontend_get_streaming_output())
    output_stats(d, "recording", obs.obs_frontend_get_recording_output())

    local temporary = destination .. ".tmp"
    local f = io.open(temporary, "w")
    if f ~= nil then
        f:write(obs.obs_data_get_json(d))
        f:close()
        os.rename(temporary, destination)
    end
    obs.obs_data_release(d)
end

function script_description()
    return "Read-only frame and output counters, sampled every two seconds. Writes no credentials and does not change or start/stop outputs."
end

function script_defaults(settings)
    obs.obs_data_set_default_string(settings, "destination", (os.getenv("HOME") or "/tmp") .. "/jev-obs/performance-status.json")
end

function script_properties()
    local properties = obs.obs_properties_create()
    obs.obs_properties_add_text(properties, "destination", "Status JSON path (existing directory)", obs.OBS_TEXT_DEFAULT)
    return properties
end

function script_update(settings)
    destination = obs.obs_data_get_string(settings, "destination")
end

function script_load(settings)
    script_update(settings)
    initialize_media_api()
    obs.timer_add(sample, 2000)
end

function script_unload()
    obs.timer_remove(sample)
end
