local obs = obslua
local root = "/home/ubuntu/jev-obs/"
local initialized = false
local frames_ready = 0
local screenshot_taken = false

local function configure_item(scene, source, left, top, width, height)
    local item = obs.obs_scene_find_source(scene, obs.obs_source_get_name(source))
    if item == nil then item = obs.obs_scene_add(scene, source) end
    local position = obs.vec2()
    position.x = left
    position.y = top
    obs.obs_sceneitem_set_pos(item, position)
    local bounds = obs.vec2()
    bounds.x = width
    bounds.y = height
    obs.obs_sceneitem_set_bounds_type(item, obs.OBS_BOUNDS_SCALE_INNER)
    obs.obs_sceneitem_set_bounds(item, bounds)
    obs.obs_sceneitem_set_bounds_alignment(item, 0)
    obs.obs_sceneitem_set_alignment(item, 5)
    return item
end

local function get_or_create(kind, name, settings)
    local source = obs.obs_get_source_by_name(name)
    if source ~= nil then
        obs.obs_source_update(source, settings)
        return source
    end
    return obs.obs_source_create(kind, name, settings, nil)
end

local function setup()
    if initialized then return end
    local file = io.open(root .. "media.json", "r")
    if file == nil then return end
    local settings = obs.obs_data_create_from_json(file:read("*a"))
    file:close()
    local media = obs.obs_get_source_by_name("JEV Factorio VM")
    if media == nil then media = get_or_create("ffmpeg_source", "JEV Factorio VM", settings) end
    obs.obs_data_release(settings)
    if media == nil then return end
    obs.obs_source_set_muted(media, false)
    local browser_settings = obs.obs_data_create()
    obs.obs_data_set_string(browser_settings, "url", "http://127.0.0.1:8765/?overlay=1")
    obs.obs_data_set_int(browser_settings, "width", 1920)
    obs.obs_data_set_int(browser_settings, "height", 1080)
    obs.obs_data_set_int(browser_settings, "fps", 30)
    obs.obs_data_set_bool(browser_settings, "shutdown", false)
    obs.obs_data_set_string(browser_settings, "css", "")
    local overlay = get_or_create("browser_source", "JEV Mission HUD", browser_settings)
    obs.obs_data_set_string(browser_settings, "url", "http://127.0.0.1:8765/?studio=1")
    local dashboard = get_or_create("browser_source", "JEV Mission Control UI", browser_settings)
    obs.obs_data_release(browser_settings)
    local source = obs.obs_get_source_by_name("JEV Factorio")
    if source == nil then
        local scene = obs.obs_scene_create("JEV Factorio")
        source = obs.obs_scene_get_source(scene)
        obs.obs_source_get_ref(source)
        obs.obs_scene_release(scene)
    end
    local native_scene = obs.obs_scene_from_source(source)
    configure_item(native_scene, media, 0, 0, 1920, 1080)
    if overlay ~= nil then configure_item(native_scene, overlay, 0, 0, 1920, 1080) end
    local dashboard_scene_source = obs.obs_get_source_by_name("JEV Mission Control")
    if dashboard_scene_source == nil and dashboard ~= nil then
        local scene = obs.obs_scene_create("JEV Mission Control")
        dashboard_scene_source = obs.obs_scene_get_source(scene)
        obs.obs_source_get_ref(dashboard_scene_source)
        obs.obs_scene_release(scene)
    end
    if dashboard_scene_source ~= nil then
        local scene = obs.obs_scene_from_source(dashboard_scene_source)
        if dashboard ~= nil then configure_item(scene, dashboard, 0, 0, 1920, 1080) end
        configure_item(scene, media, 277, 111, 1342, 754.875)
        if dashboard ~= nil then
            local dashboard_item = obs.obs_scene_find_source(scene, "JEV Mission Control UI")
            obs.obs_sceneitem_set_order(dashboard_item, obs.OBS_ORDER_MOVE_TOP)
        end
        obs.obs_source_release(dashboard_scene_source)
    end
    local marker = io.open(root .. "initialized", "r")
    if marker ~= nil then
        marker:close()
    elseif not obs.obs_frontend_streaming_active() and not obs.obs_frontend_recording_active() then
        obs.obs_frontend_set_current_scene(source)
        local saved = io.open(root .. "initialized", "w")
        if saved ~= nil then saved:write("configured\n"); saved:close() end
    end
    obs.obs_frontend_save()
    obs.obs_source_release(source)
    obs.obs_source_release(media)
    if overlay ~= nil then obs.obs_source_release(overlay) end
    if dashboard ~= nil then obs.obs_source_release(dashboard) end
    initialized = true
end

local function tick()
    setup()
    local capture = io.open(root .. "screenshot.request", "r")
    if capture ~= nil then
        capture:close()
        os.remove(root .. "screenshot.request")
        obs.obs_frontend_take_screenshot()
    end
    local request = io.open(root .. "open-projector.request", "r")
    if request ~= nil then
        request:close()
        obs.obs_frontend_open_projector("Source", -1, "", "JEV Factorio VM")
        os.remove(root .. "open-projector.request")
        local opened = io.open(root .. "projector-opened.json", "w")
        if opened ~= nil then
            opened:write(string.format('{"source":"JEV Factorio VM","opened_epoch":%d}', os.time()))
            opened:close()
        end
        obs.obs_frontend_save()
    end
    local status = obs.obs_data_create()
    obs.obs_data_set_int(status, "updated_epoch", os.time())
    obs.obs_data_set_bool(status, "initialized", initialized)
    obs.obs_data_set_bool(status, "recording", obs.obs_frontend_recording_active())
    obs.obs_data_set_bool(status, "streaming", obs.obs_frontend_streaming_active())
    local scene = obs.obs_frontend_get_current_scene()
    if scene ~= nil then
        obs.obs_data_set_string(status, "scene", obs.obs_source_get_name(scene))
        obs.obs_source_release(scene)
    end
    local source = obs.obs_get_source_by_name("JEV Factorio VM")
    if source ~= nil then
        local width = obs.obs_source_get_width(source)
        local height = obs.obs_source_get_height(source)
        local state = obs.obs_source_media_get_state(source)
        obs.obs_data_set_int(status, "width", width)
        obs.obs_data_set_int(status, "height", height)
        obs.obs_data_set_int(status, "media_state", state)
        obs.obs_data_set_int(status, "media_time_ms", obs.obs_source_media_get_time(source))
        if width > 0 and height > 0 and state == obs.OBS_MEDIA_STATE_PLAYING then
            frames_ready = frames_ready + 1
            if frames_ready >= 8 and not screenshot_taken then
                obs.obs_frontend_take_screenshot()
                screenshot_taken = true
            end
        end
        obs.obs_source_release(source)
    end
    local screenshot = obs.obs_frontend_get_last_screenshot()
    if screenshot ~= nil then obs.obs_data_set_string(status, "screenshot", screenshot) end
    local file = io.open(root .. "status.json.tmp", "w")
    if file ~= nil then
        file:write(obs.obs_data_get_json(status))
        file:close()
        os.rename(root .. "status.json.tmp", root .. "status.json")
    end
    obs.obs_data_release(status)
end

function script_description()
    return "JEV: private Factorio VM video, read-only mission control scenes, and local source health. Does not start recording or streaming."
end

function script_load(settings)
    obs.timer_add(tick, 1000)
end

function script_unload()
    obs.timer_remove(tick)
end
