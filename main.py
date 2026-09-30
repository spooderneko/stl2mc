import os
import zlib
import trimesh
import ctypes
import multiprocessing
import numpy as np
import dearpygui.dearpygui as dpg
from scipy.ndimage import binary_erosion, binary_fill_holes


# --- GLOBAL VARIABLES ---
INPUT_DIR = "input"
OUTPUT_DIR = "output"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
current_model_path = None
voxel_matrix = None
viewer_process = None
shared_z = multiprocessing.Value(ctypes.c_int, 0)

# Memory vars
last_z_max = 100
last_fill = 0.0
last_rot_x = 0.0
last_rot_y = 0.0
last_rot_z = 0.0


# --- FUNCTIONS ---
def load_file_dialog_callback(sender, app_data):
    global current_model_path
    if "file_path_name" in app_data:
        current_model_path = app_data['file_path_name']
        dpg.set_value("current_file_text", f"File: {os.path.basename(current_model_path)}")
        process_mesh()

def process_mesh(sender = None, app_data = None, user_data = None):
    global current_model_path, voxel_matrix, viewer_process
    global last_z_max, last_fill, last_rot_x, last_rot_y, last_rot_z

    if not current_model_path or not os.path.exists(current_model_path):
        return

    # Get UI Values
    z_max = last_z_max = int(dpg.get_value("z_max_input") or 100)
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

    dpg.set_value("status_text", f"Status : Generation done ({np.sum(voxel_matrix)} voxels) - Final Zmax {max_z_index + 1}")

    # Calculate block quantities
    total_voxels = int(np.sum(voxel_matrix))
    if total_voxels > 0:
        stacks = total_voxels / 64.0
        chests = total_voxels / (64.0*27.0)
        double_chests = total_voxels / (64.0*27.0*2)

        bom_text = (
                f"Total : {total_voxels} blocks\n"
                f"- {stacks:.1f} Stacks (64)\n"
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
        viewer_process = multiprocessing.Process(target=_run_3d_viewer, args=(voxel_matrix, shared_z))
        viewer_process.start()

def _run_3d_viewer(matrix, shared_z_obj):
    import trimesh
    import numpy as np

    # Generates blue and grey cubes for a given Z value
    def build_meshes(z_target):
        meshes = {}
        
        # Gray cubes
        gray_matrix = np.copy(matrix)
        gray_matrix[:, :, z_target:] = False
        if np.any(gray_matrix):
            gray_mesh = trimesh.voxel.VoxelGrid(gray_matrix).as_boxes()
            centers = gray_mesh.triangles_center
            checker = (np.floor(centers[:, 0]) + np.floor(centers[:, 1]) + np.floor(centers[:, 2])) % 2 == 0
            colors = np.full((len(centers), 4), [150, 150, 150, 255])
            colors[checker] = [130, 130, 130, 255]
            gray_mesh.visual.face_colors = colors
            meshes['gray_blocks'] = gray_mesh

        # Blue cubes
        blue_matrix = np.zeros_like(matrix)
        blue_matrix[:, :, z_target] = matrix[:, :, z_target]
        if np.any(blue_matrix):
            blue_mesh = trimesh.voxel.VoxelGrid(blue_matrix).as_boxes()
            centers = blue_mesh.triangles_center
            checker = (np.floor(centers[:, 0]) + np.floor(centers[:, 1]) + np.floor(centers[:, 2])) % 2 == 0
            colors = np.full((len(centers), 4), [50, 150, 255, 255])
            colors[checker] = [30, 110, 210, 255]
            blue_mesh.visual.face_colors = colors
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
    global voxel_matrix, viewer_process, shared_z
    if voxel_matrix is None:
        return

    shared_z.value = dpg.get_value("layer_input")

    if viewer_process is None or not viewer_process.is_alive():
        viewer_process = multiprocessing.Process(target=_run_3d_viewer, args=(voxel_matrix,shared_z))
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
                dpg.add_input_int(label="Max Height (Z)", default_value=100, tag="z_max_input")
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

            # Right column = all the space not used by the left column = viewer and its settings
            with dpg.child_window(border=False): # type: ignore yea yea i know
                with dpg.group(horizontal=True): # type: ignore .......
                    dpg.add_input_int(label="Current layer (Z)", default_value=0, min_value=0, max_value=0, tag="layer_input", callback=update_2d_view, width=150, step=1)
                    dpg.add_button(label="Center view (reset camera)", callback=lambda: (dpg.fit_axis_data("x_axis"), dpg.fit_axis_data("y_axis")))
                
                with dpg.plot(label="Cross section plane", height=-1, width=-1, no_menus=True, no_mouse_pos=True, equal_aspects=True): # type: ignore
                    dpg.add_plot_legend(show=False)
                    dpg.add_plot_axis(dpg.mvXAxis, label="X", tag="x_axis", no_gridlines=True, no_tick_marks=True, no_tick_labels=True)
                    with dpg.plot_axis(dpg.mvYAxis, label="Y", tag="y_axis", no_gridlines=True, no_tick_marks=True, no_tick_labels=True): # type: ignore
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
        