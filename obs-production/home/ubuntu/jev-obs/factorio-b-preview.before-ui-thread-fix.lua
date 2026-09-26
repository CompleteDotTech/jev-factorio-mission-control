local obs = obslua
local root = "/home/ubuntu/jev-obs/"
local configured = false
local source_name = "Factorio B - Dev Video"
local scene_name = "Factorio B - Preview"
local function setup()
 if configured then return end
 local f = io.open(root .. "factorio-b-media.json", "r")
 if f == nil then return end
 local settings = obs.obs_data_create_from_json(f:read("*a")); f:close()
 local media = obs.obs_get_source_by_name(source_name)
 if media == nil then media = obs.obs_source_create("ffmpeg_source", source_name, settings, nil) end
 obs.obs_data_release(settings)
 if media == nil then return end
 obs.obs_source_set_muted(media, true)
 local source = obs.obs_get_source_by_name(scene_name)
 if source == nil then
  local scene = obs.obs_scene_create(scene_name)
  source = obs.obs_scene_get_source(scene); obs.obs_source_get_ref(source)
  obs.obs_scene_release(scene)
 end
 local scene = obs.obs_scene_from_source(source)
 local item = obs.obs_scene_find_source(scene, source_name)
 if item == nil then item = obs.obs_scene_add(scene, media) end
 local bounds = obs.vec2(); bounds.x = 1920; bounds.y = 1080
 obs.obs_sceneitem_set_bounds_type(item, obs.OBS_BOUNDS_SCALE_INNER)
 obs.obs_sceneitem_set_bounds(item, bounds)
 obs.obs_sceneitem_set_bounds_alignment(item, 0)
 local pos = obs.vec2(); pos.x = 0; pos.y = 0
 obs.obs_sceneitem_set_pos(item, pos)
 obs.obs_sceneitem_set_alignment(item, 5)
 obs.obs_frontend_set_preview_program_mode(true)
 obs.obs_frontend_set_current_preview_scene(source)
 obs.obs_frontend_save()
 obs.obs_source_release(source); obs.obs_source_release(media)
 configured = true
end
local function tick()
 setup()
 local d = obs.obs_data_create()
 obs.obs_data_set_int(d, "updated_epoch", os.time())
 obs.obs_data_set_bool(d, "streaming", obs.obs_frontend_streaming_active())
 obs.obs_data_set_bool(d, "studio_mode", obs.obs_frontend_preview_program_mode_active())
 local program = obs.obs_frontend_get_current_scene()
 if program ~= nil then obs.obs_data_set_string(d, "program_scene", obs.obs_source_get_name(program)); obs.obs_source_release(program) end
 local preview = obs.obs_frontend_get_current_preview_scene()
 if preview ~= nil then obs.obs_data_set_string(d, "preview_scene", obs.obs_source_get_name(preview)); obs.obs_source_release(preview) end
 local media = obs.obs_get_source_by_name(source_name)
 if media ~= nil then
  obs.obs_data_set_int(d, "width", obs.obs_source_get_width(media))
  obs.obs_data_set_int(d, "height", obs.obs_source_get_height(media))
  obs.obs_data_set_int(d, "media_state", obs.obs_source_media_get_state(media))
  obs.obs_data_set_int(d, "media_time_ms", obs.obs_source_media_get_time(media))
  obs.obs_data_set_bool(d, "muted", obs.obs_source_muted(media))
  local req = io.open(root .. "factorio-b-screenshot.request", "r")
  if req ~= nil then
   req:close(); os.remove(root .. "factorio-b-screenshot.request")
   obs.obs_frontend_take_source_screenshot(media)
  end
  obs.obs_source_release(media)
 end
 local path = obs.obs_frontend_get_last_screenshot()
 if path ~= nil then obs.obs_data_set_string(d, "last_screenshot", path) end
 local f = io.open(root .. "factorio-b-status.json.tmp", "w")
 if f ~= nil then f:write(obs.obs_data_get_json(d)); f:close(); os.rename(root .. "factorio-b-status.json.tmp",root .. "factorio-b-status.json") end
 obs.obs_data_release(d)
end
function script_description() return "Isolated Factorio B development preview. Never switches program or starts/stops streaming. Audio muted." end
function script_load(settings) obs.timer_add(tick, 1000) end
function script_unload() obs.timer_remove(tick) end
