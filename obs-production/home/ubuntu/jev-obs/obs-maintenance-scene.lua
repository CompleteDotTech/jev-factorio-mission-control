obs = obslua
local scene_name = 'JEV - Maintenance'
local source_name = 'JEV Maintenance Image'
local image_path = '/home/ubuntu/jev-obs/assets/jev-factorio-maintenance-v1.png'

function script_description()
    return 'Install the JEV maintenance image scene without switching the live program.'
end

local function install()
    obs.timer_remove(install)
    local file = io.open(image_path, 'rb')
    if not file then error('Maintenance image is missing') end
    file:close()
    local info = obs.obs_video_info()
    if not obs.obs_get_video_info(info) then error('No active video canvas') end
    local existing = obs.obs_get_source_by_name(scene_name)
    if existing and not obs.obs_scene_from_source(existing) then
        obs.obs_source_release(existing)
        error('Maintenance scene name conflict')
    end
    local current = obs.obs_frontend_get_current_scene()
    local before = current and obs.obs_source_get_name(current) or ''
    if current then obs.obs_source_release(current) end
    local settings = obs.obs_data_create()
    obs.obs_data_set_string(settings, 'file', image_path)
    local source = obs.obs_get_source_by_name(source_name)
    if source then
        local saved = obs.obs_source_get_settings(source)
        local valid = obs.obs_source_get_id(source) == 'image_source'
            and obs.obs_data_get_string(saved, 'file') == image_path
        obs.obs_data_release(saved)
        if not valid then
            obs.obs_source_release(source)
            obs.obs_data_release(settings)
            if existing then obs.obs_source_release(existing) end
            error('Maintenance source conflict')
        end
    else
        source = obs.obs_source_create('image_source', source_name, settings, nil)
    end
    obs.obs_data_release(settings)
    if not source then
        if existing then obs.obs_source_release(existing) end
        error('Could not create image source')
    end
    local scene
    if existing then scene = obs.obs_scene_from_source(existing)
    else scene = obs.obs_scene_create(scene_name) end
    if not scene then
        obs.obs_source_release(source)
        if existing then obs.obs_source_release(existing) end
        error('Could not create maintenance scene')
    end
    local item = obs.obs_scene_find_source(scene, source_name) or obs.obs_scene_add(scene, source)
    local bounds = obs.vec2()
    bounds.x = info.base_width
    bounds.y = info.base_height
    -- OBS Lua does not export the C alignment macros in all versions.
    obs.obs_sceneitem_set_alignment(item, 5) -- LEFT (1) | TOP (4)
    obs.obs_sceneitem_set_bounds_type(item, 2) -- OBS_BOUNDS_SCALE_INNER
    obs.obs_sceneitem_set_bounds_alignment(item, 0)
    obs.obs_sceneitem_set_bounds(item, bounds)
    local position = obs.vec2()
    position.x = 0
    position.y = 0
    obs.obs_sceneitem_set_pos(item, position)
    obs.obs_sceneitem_set_visible(item, true)
    obs.obs_sceneitem_set_locked(item, true)
    obs.obs_source_release(source)
    if existing then obs.obs_source_release(existing) else obs.obs_scene_release(scene) end
    obs.obs_frontend_save()
    current = obs.obs_frontend_get_current_scene()
    local after = current and obs.obs_source_get_name(current) or ''
    if current then obs.obs_source_release(current) end
    obs.script_log(obs.LOG_INFO, 'Maintenance installed; program before=' .. before .. '; after=' .. after)
end

function script_load(settings)
    obs.timer_add(install, 1000)
end

function script_unload()
    obs.timer_remove(install)
end
