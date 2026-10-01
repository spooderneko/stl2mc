import os
import zlib
import trimesh
import ctypes
import multiprocessing
import numpy as np
import dearpygui.dearpygui as dpg
from litemapy import Schematic, Region, BlockState
from scipy.ndimage import binary_erosion, binary_fill_holes, convolve


# --- GLOBAL VARIABLES ---
INPUT_DIR = "input"
OUTPUT_DIR = "output"
BLOCKS_DIR = "block_lists"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(BLOCKS_DIR, exist_ok=True)

current_model_path = None
voxel_matrix = None
viewer_process = None
shared_z = multiprocessing.Value(ctypes.c_int, 0)
current_minecraft_blocks = {}

# Lighting global caches (so export can use them)
ao_scores = None
sun_light = None

# Memory vars
last_z_max = 100
last_fill = 0.0
last_rot_x = 0.0
last_rot_y = 0.0
last_rot_z = 0.0


# --- PREP FUNCTIONS ---
if not any(f.endswith('.conf') for f in os.listdir(BLOCKS_DIR)):
    with open(os.path.join(BLOCKS_DIR, "default.conf"), "w") as f:
        f.write("White Concrete=minecraft:white_concrete=225,226,227\n")
        f.write("Light Gray Concrete=minecraft:light_gray_concrete=125,125,121\n")
        f.write("Gray Concrete=minecraft:gray_concrete=54,57,61\n")
        f.write("Black Concrete=minecraft:black_concrete=8,10,15\n")
        

# --- FUNCTIONS ---
def load_blocks_from_file(filename):
    blocks = []
    filepath = os.path.join(BLOCKS_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    parts = line.strip().split('=')
                    if len(parts) >= 3:
                        name, block_id = parts[0].strip(), parts[1].strip()
                        r, g, b = map(int, parts[2].split(','))
                        # Luminance formula
                        lum = 0.299*r + 0.587*g + 0.114*b
                        blocks.append({
                            "name": name, 
                            "id": block_id, 
                            "color": [r, g, b, 255],
                            "lum": lum
                        })
    # Brightest first
    #! WARNING: ONLY USABLE IN GRAYSCALE
    blocks.sort(key=lambda x: x["lum"], reverse=True)
    return blocks

def on_config_changed(sender, app_data, user_data):
    global current_minecraft_blocks
    current_minecraft_blocks = load_blocks_from_file(app_data)
    block_names = [b["name"] for b in current_minecraft_blocks]
    default_val = block_names[0] if block_names else ""
    dpg.configure_item("material_input", items=block_names, default_value=default_val)


def load_file_dialog_callback(sender, app_data):
    global current_model_path
    if "file_path_name" in app_data:
        current_model_path = app_data['file_path_name']
        dpg.set_value("current_file_text", f"File: {os.path.basename(current_model_path)}")
        process_mesh()

def process_mesh(sender = None, app_data = None, user_data = None):
    global current_model_path, voxel_matrix, viewer_process
    global last_z_max, last_fill, last_rot_x, last_rot_y, last_rot_z
    global ao_scores, sun_light

    if not current_model_path or not os.path.exists(current_model_path):
        return

    # Get UI Values
    z_max = last_z_max = int(dpg.get_value("z_max_input") or 50)  # Better than 100 and less calculation time
    fill_percent = last_fill = float(dpg.get_value("fill_input") or 0.0)
    rot_x = last_rot_x = float(dpg.get_value("rot_x_input") or 0.0)
    rot_y = last_rot_y = float(dpg.get_value("rot_y_input") or 0.0)
    rot_z = last_rot_z = float(dpg.get_value("rot_z_input") or 0.0)

    # Check if the loaded object is a valid mesh (or .matrix will not work)
    mesh = trimesh.load(current_model_path, force='mesh')
    if not isinstance(mesh, trimesh.Trimesh):
        dpg.set_value("status_text", "Error : the file does not contain a valid 3D mesh.")
        return

    # Apply rotation
    mat_x = trimesh.transformations.rotation_matrix(np.radians(rot_x), [1, 0, 0])
    mat_y = trimesh.transformations.rotation_matrix(np.radians(rot_y), [0, 1, 0])
    mat_z = trimesh.transformations.rotation_matrix(np.radians(rot_z), [0, 0, 1])
    transform_matrix = trimesh.transformations.concatenate_matrices(mat_x, mat_y, mat_z)
    mesh.apply_transform(transform_matrix)

    # Scale based on max height
    scale_factor = z_max / mesh.extents[2]
    mesh.apply_scale(scale_factor)

    # Voxel here
    # Note: Scale might be adjusted based on the block used in Minecraft ? (if using rods)
    voxel_grid = mesh.voxelized(pitch=1.0)
    surface_matrix = np.array(voxel_grid.matrix, dtype=bool)  # type: ignore (isinstance above ensures this is a VoxelGrid)
    solid_matrix = np.array(binary_fill_holes(surface_matrix), dtype=bool)

    # Hollowing, keeping 1 layer of voxels
    eroded_inside = binary_erosion(solid_matrix).astype(bool)
    shell = solid_matrix & ~eroded_inside

    if fill_percent == 0.0:
        matrix_3d = shell

    elif fill_percent >= 100.0:
        matrix_3d = solid_matrix

    else:
        file_seed = zlib.crc32(current_model_path.encode('utf-8')) & 0xffffffff
        np.random.seed(file_seed)
        probability_mask = np.random.rand(*solid_matrix.shape) < (fill_percent / 100.0)
        matrix_3d = shell | (eroded_inside & probability_mask)

    voxel_matrix = matrix_3d
    max_z_index = voxel_matrix.shape[2] - 1

    # Avoid setting the layer input to a value higher than the max Z index or reset to 0 each time, keep the current layer if possible
    current_layer = dpg.get_value("layer_input")
    dpg.configure_item("layer_input", max_value=max_z_index)
    if current_layer > max_z_index:
        dpg.set_value("layer_input", max_z_index)

    # Pre compute lighting
    sun_light = np.zeros_like(voxel_matrix, dtype=bool)
    for x in range(voxel_matrix.shape[0]):
        for y in range(voxel_matrix.shape[1]):
            z_i = np.where(voxel_matrix[x, y, :])[0]
            if len(z_i) > 0:
                sun_light[x, y, z_i[-1]] = True

    kernel = np.ones((3, 3, 3), dtype=int)
    kernel[1, 1, 1] = 0
    ao_scores = convolve(voxel_matrix.astype(int), kernel, mode="constant", cval=0)

    dpg.set_value("status_text", f"Status : Generation done ({np.sum(voxel_matrix)} voxels) - Final Zmax {max_z_index + 1}")

    # Calculate block quantities
    total_voxels = int(np.sum(voxel_matrix))
    if total_voxels > 0:
        stacks = total_voxels / 64.0
        chests = total_voxels / (64.0*27.0)
        double_chests = total_voxels / (64.0*27.0*2)

        bom_text = (
                f"Total : {total_voxels} blocks\n"
                f"- {stacks:.1f} Stacks\n"  # Easier to read
                f"- {chests:.1f} Simple chests\n"
                f"- {double_chests:.1f} Double chests"
            )
    else:
        bom_text = "No block generated"
    dpg.set_value("bom_text", bom_text)

    # Freeze the zoom 
    dpg.fit_axis_data("x_axis")
    dpg.fit_axis_data("y_axis")
    update_2d_view()

    if viewer_process is not None and viewer_process.is_alive():
        viewer_process.terminate()
        viewer_process.join()
        viewer_process = multiprocessing.Process(target=_run_3d_viewer, args=(voxel_matrix, shared_z, ao_scores, sun_light, current_minecraft_blocks))
        viewer_process.start()

def _run_3d_viewer(matrix, shared_z_obj, ao, sun, blocks_palette):
    import trimesh
    import numpy as np

    palette_colors = [b["color"] for b in blocks_palette] if blocks_palette else [[180, 180, 180, 255]]
    num_colors = len(palette_colors)

    # Generates blue and grey cubes for a given Z value
    def build_meshes(z_target):
        meshes = {}

        def apply_lighting(mesh_obj, is_active_layer):
            centers = mesh_obj.triangles_center
            coords = np.round(centers).astype(int)
            cx = np.clip(coords[:, 0], 0, matrix.shape[0]-1)
            cy = np.clip(coords[:, 1], 0, matrix.shape[1]-1)
            cz = np.clip(coords[:, 2], 0, matrix.shape[2]-1)

            scores = ao[cx, cy, cz]
            is_sunlit = sun[cx, cy, cz]
            colors = np.zeros((len(centers), 4), dtype=np.uint8)

            if is_active_layer:
                b_colors = [
                    [70, 160, 240, 255], [40, 120, 215, 255],
                    [20, 90, 180, 255], [10, 60, 140, 255]
                ]
                colors = np.full((len(centers), 4), b_colors[1])
                colors[scores >= 11] = b_colors[2]
                colors[scores >= 20] = b_colors[3]
                colors[is_sunlit] = b_colors[0]
            else:
                if num_colors == 0:
                    colors = np.full((len(centers), 4), [180, 180, 180, 255])
                elif num_colors == 1:
                    colors = np.full((len(centers), 4), palette_colors[0])
                else:
                    colors = np.full((len(centers), 4), palette_colors[1])
                    if num_colors == 4:
                        colors[scores >= 11] = palette_colors[2]
                        colors[scores >= 20] = palette_colors[3]
                    else:
                        idx = 1 + np.floor((scores / 26.0) * (num_colors - 1)).astype(int)
                        idx = np.clip(idx, 1, num_colors - 1)
                        for i in range(1, num_colors):
                            colors[idx == i] = palette_colors[i]

                    colors[is_sunlit] = palette_colors[0]

            mesh_obj.visual.face_colors = colors
            return mesh_obj
        
        # Gray cubes
        gray_matrix = np.copy(matrix)
        gray_matrix[:, :, z_target:] = False
        if np.any(gray_matrix):
            gray_mesh = trimesh.voxel.VoxelGrid(gray_matrix).as_boxes()
            gray_mesh = apply_lighting(gray_mesh, is_active_layer=False)
            meshes['gray_blocks'] = gray_mesh

        # Blue cubes
        blue_matrix = np.zeros_like(matrix)
        blue_matrix[:, :, z_target] = matrix[:, :, z_target]
        if np.any(blue_matrix):
            blue_mesh = trimesh.voxel.VoxelGrid(blue_matrix).as_boxes()
            blue_mesh = apply_lighting(blue_mesh, is_active_layer=True)
            meshes['blue_blocks'] = blue_mesh
            
        return meshes

    # Init scene (or white screen :c)
    current_z = shared_z_obj.value
    scene = trimesh.Scene()
    
    # Add to the scene before showing so camera is not lost
    initial_meshes = build_meshes(current_z)
    for name, mesh in initial_meshes.items():
        scene.add_geometry(mesh, geom_name=name)

    # Update loop
    def update_scene(current_scene):
        nonlocal current_z
        z_target = shared_z_obj.value

        if z_target != current_z:
            # Clean
            if 'gray_blocks' in current_scene.geometry:
                current_scene.delete_geometry('gray_blocks')
            if 'blue_blocks' in current_scene.geometry:
                current_scene.delete_geometry('blue_blocks')

            # Add new blocks
            new_meshes = build_meshes(z_target)
            for name, mesh in new_meshes.items():
                current_scene.add_geometry(mesh, geom_name=name)

            current_z = z_target

    scene.show(callback=update_scene, smooth=False)

def show_real_3d_viewer():
    global voxel_matrix, viewer_process, shared_z, ao_scores, sun_light, current_minecraft_blocks
    if voxel_matrix is None:
        return

    shared_z.value = dpg.get_value("layer_input")

    if viewer_process is None or not viewer_process.is_alive():
        viewer_process = multiprocessing.Process(target=_run_3d_viewer, args=(voxel_matrix,shared_z, ao_scores, sun_light, current_minecraft_blocks))
        viewer_process.start()

def update_2d_view(sender=None, app_data=None, user_data=None):
    global voxel_matrix, viewer_process, shared_z
    if voxel_matrix is None:
        return

    z_current = dpg.get_value("layer_input")

    if dpg.does_item_exist("series_shadow"): dpg.delete_item("series_shadow")
    if dpg.does_item_exist("series_current"): dpg.delete_item("series_current")
    if dpg.does_item_exist("series_3d"): dpg.delete_item("series_3d")

    if z_current > 0:
        x_sh, y_sh = np.where(voxel_matrix[:, :, z_current - 1])
        if len(x_sh) > 0:
            dpg.add_scatter_series(x_sh.tolist(), y_sh.tolist(), tag="series_shadow", parent="y_axis")
            with dpg.theme() as shadow_theme: # type: ignore yea yea i know
                with dpg.theme_component(dpg.mvScatterSeries): # type: ignore yea yea i know
                    dpg.add_theme_color(dpg.mvPlotCol_Line, (150, 150, 150, 100), category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_style(dpg.mvPlotStyleVar_MarkerSize, 6, category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_style(dpg.mvPlotStyleVar_Marker, dpg.mvPlotMarker_Square, category=dpg.mvThemeCat_Plots)
            dpg.bind_item_theme("series_shadow", shadow_theme)

    x_cur, y_cur = np.where(voxel_matrix[:, :, z_current])
    if len(x_cur) > 0:
        dpg.add_scatter_series(x_cur.tolist(), y_cur.tolist(), tag="series_current", parent="y_axis")
        with dpg.theme() as current_theme: # type: ignore yea yea i know
            with dpg.theme_component(dpg.mvScatterSeries): # type: ignore yea yea i know
                dpg.add_theme_color(dpg.mvPlotCol_Line, (50, 150, 255, 255), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_MarkerSize, 8, category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_Marker, dpg.mvPlotMarker_Square, category=dpg.mvThemeCat_Plots)
            dpg.bind_item_theme("series_current", current_theme)

    shared_z.value = z_current

def export_to_litematic(sender=None, app_data=None, user_data=None):
    global voxel_matrix, current_model_path, current_minecraft_blocks, ao_scores, sun_light
    
    if voxel_matrix is None or not np.any(voxel_matrix) or not isinstance(current_model_path, str):
        dpg.set_value("status_text", "Error: Generate a model first.")
        return

    dpg.set_value("status_text", "Export in progress, please wait...")

    use_palette = dpg.get_value("use_palette_checkbox")
    num_colors = len(current_minecraft_blocks)

    #! Minecraft axes : X Z flat then Y height
    #! This code axes : X Y flat then Z height
    max_x, max_y, max_z = voxel_matrix.shape 
    reg = Region(0, 0, 0, max_x, max_z, max_y)  # Swap Y and Z here
    
    base_name = os.path.splitext(os.path.basename(current_model_path))[0]
    schem = Schematic(
        name=base_name, 
        author="STL2MC", 
        description="Structure generated using STL2MC", 
        regions={"main": reg}
    )

    # Reverted too because blocks must be placed with the same way as the region above
    xs, ys, zs = np.where(voxel_matrix)
    for x, y, z in zip(xs, ys, zs):
        # Block mapping
        if use_palette and num_colors > 0 and ao_scores is not None and sun_light is not None: 
            sc = ao_scores[x, y, z]
            sun = sun_light[x, y, z]

            if sun:
                idx = 0
            elif num_colors == 4:
                idx = 1 if sc < 11 else (2 if sc < 20 else 3)
            elif num_colors > 1:
                idx = 1 + int((sc / 26.0) * (num_colors - 1)) # Since max ao score = 26
                idx = min(idx, num_colors - 1)
            else:
                idx = 0

            block_id = current_minecraft_blocks[idx]["id"]

        # Single block mapping
        else:
            selected_name = dpg.get_value("material_input")
            block_id = "minecraft:stone"
            for b in current_minecraft_blocks:
                if b["name"] == selected_name:
                    block_id = b["id"]
                    break

        block = BlockState(block_id)
        reg[int(x), int(z), int(y)] = block

    # Save in output folder
    export_path = os.path.join(OUTPUT_DIR, f"{base_name}.litematic")
    schem.save(export_path)
    
    dpg.set_value("status_text", f"Success : Exported to {export_path}")



def cancel_changes(sender=None, app_data=None, user_data=None):
    dpg.set_value("z_max_input", last_z_max)
    dpg.set_value("fill_input", last_fill)
    dpg.set_value("rot_x_input", last_rot_x)
    dpg.set_value("rot_y_input", last_rot_y)
    dpg.set_value("rot_z_input", last_rot_z)

# --- GUI SETUP // RUN ---
if __name__ == "__main__":
    dpg.create_context()
    dpg.create_viewport(title='STL to Minecraft', width=1200, height=800)

    with dpg.file_dialog(directory_selector=False, show=False, callback=load_file_dialog_callback, tag="file_dialog_id", width=600, height=400, default_path=INPUT_DIR):  # type: ignore
        dpg.add_file_extension(".stl", color=(0, 255, 0, 255))
        dpg.add_file_extension(".*")

    # Main window with layout
    with dpg.window(tag="main_window"): # type: ignore yea yea i know
        
        # Horizontal group (side by side)
        with dpg.group(horizontal=True): # type: ignore yea yea i know
            
            # Left column => controls and settings
            with dpg.child_window(width=350, border=False): # type: ignore yea yea i know
                dpg.add_button(label="Select a STL file", callback=lambda: dpg.show_item("file_dialog_id"), width=-1)
                dpg.add_text("File: None", tag="current_file_text", wrap=330)
                
                dpg.add_separator()
                dpg.add_input_int(label="Max Height (Z)", default_value=50, tag="z_max_input")
                dpg.add_input_float(label="Fill (%)", default_value=0.0, step=10.0, tag="fill_input")
                
                dpg.add_separator()
                dpg.add_text("Rotations (Degrees)")
                dpg.add_input_float(label="Rotation X axis", default_value=0.0, step=90.0, tag="rot_x_input")
                dpg.add_input_float(label="Rotation Y axis", default_value=0.0, step=90.0, tag="rot_y_input")
                dpg.add_input_float(label="Rotation Z axis", default_value=0.0, step=90.0, tag="rot_z_input")
                
                dpg.add_separator()
                with dpg.group(horizontal=True): # type: ignore yea yea i know
                    dpg.add_button(label="Cancel", callback=cancel_changes, width=165)
                    dpg.add_button(label="Apply", callback=process_mesh, width=165)
                dpg.add_text("Statut : Standby...", tag="status_text", color=(100, 255, 100), wrap=330)

                dpg.add_separator()
                dpg.add_text("Blocks list", color=(255, 200, 100))
                dpg.add_text("Standby...", tag="bom_text", wrap=330)
                
                dpg.add_separator()
                dpg.add_button(label="Open 3D Viewer...", callback=show_real_3d_viewer, width=-1, height=50)

                dpg.add_separator()
                dpg.add_text("Export Litematica", color=(150, 200, 255))
                conf_files = [f for f in os.listdir(BLOCKS_DIR) if f.endswith('.conf')] # Load configuration files
                default_conf = conf_files[0] if conf_files else ""
                if default_conf:
                    current_minecraft_blocks = load_blocks_from_file(default_conf)

                initial_blocks = [b["name"] for b in current_minecraft_blocks] if current_minecraft_blocks else []
                default_block = initial_blocks[0] if initial_blocks else ""

                dpg.add_combo(conf_files, label="File version to use", default_value=default_conf, tag="config_file_input", callback=on_config_changed, width=-1)
                dpg.add_combo(initial_blocks, default_value=default_block, tag="material_input", width=-1)

                dpg.add_checkbox(label="Use full palette (based on lighting)", default_value=False, tag="use_palette_checkbox")
                
                dpg.add_button(label="Export to .litematic", callback=export_to_litematic, width=-1, height=40)

            # Right column = all the space not used by the left column = viewer and its settings
            with dpg.child_window(border=False): # type: ignore yea yea i know
                with dpg.group(horizontal=True): # type: ignore .......
                    dpg.add_input_int(label="Current layer (Z)", default_value=0, min_value=0, min_clamped=True, max_value=0, max_clamped=True, tag="layer_input", callback=update_2d_view, width=150, step=1)
                    dpg.add_button(label="Center view (reset camera)", callback=lambda: (dpg.fit_axis_data("x_axis"), dpg.fit_axis_data("y_axis")))
                
                with dpg.plot(label="Cross section plane", height=-1, width=-1, no_menus=True, no_mouse_pos=True, equal_aspects=True): # type: ignore
                    dpg.add_plot_legend(show=False)
                    dpg.add_plot_axis(dpg.mvXAxis, label="X", tag="x_axis", no_gridlines=False, no_tick_marks=False, no_tick_labels=False)
                    with dpg.plot_axis(dpg.mvYAxis, label="Y", tag="y_axis", no_gridlines=False, no_tick_marks=False, no_tick_labels=False): # type: ignore
                        pass  # The scatter series will be added dynamically in the update_view function

    dpg.setup_dearpygui()
    dpg.show_viewport()
    
    # Use 100% screen
    dpg.set_primary_window("main_window", True)

    while dpg.is_dearpygui_running():
        dpg.render_dearpygui_frame()

    dpg.destroy_context()
    if viewer_process is not None and viewer_process.is_alive():
        viewer_process.terminate()
        viewer_process.join()
        