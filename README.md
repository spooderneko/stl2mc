# STL to Minecraft Blueprint

An interactive Python tool to convert STL files to "building instructions" layer by layer for Minecraft.

## Features
* **2D Visualization (Cross-section):** Displays the current Z-layer alongside the previous layer (Z-1)
* **3D Visualization:** Isometric viewer synced with the 2D viewer
* **Hollowing:** Options to keep only a shell (0% infill) or a solid structure (100%). Partial filling is... meh

## Installation
1. Make sure to have Python installed (I used 3.11.7)
2. Git clone this (or download as ZIP and extract)
3. Create venv
```
# ON LINUX
python3 -m venv venv
source venv/bin/activate
```
```
# ON WINDOWS
python -m venv venv
venv\Scripts\activate
```
4. Install dependencies with
```bash
pip install -r requirements.txt
```

## Usage
Run the GUI: `python main.py`

1. First, choose a STL file (open defaults to input/ folder, so put the file in it to facilitate navigation)
2. Define settings and apply. You can use the 3D viewer to see if these settings are fine for you or change them and reapply.
3. Use the main 2D frame to navigate between the different layers in both the 2D and 3D views


## To do if im not lazy
- [ ] Convert these... things I do to litematics and world edit
- [ ] Maybe add palette colors and blocks (first implementation with shadows only)
- [x] ~~Chunk grid in red~~ => Useless ?
- [x] Convert voxels to stacks of 64, chests and double chests
- [x] Add previous layers
- [x] Add 3D View


## Author
Made by Spooder Neko 

<p align="center">
  <img src="https://media1.tenor.com/m/_CnTYao_DCwAAAAC/anime.gif" alt="Anime GIF" width="300"/>
</p>
