                                  CONFIGURATION FOR BLOCKS
                                ============================

THIS FOLDER CONTAINS BLOCK, ITS MINECRAFT ID AND ITS AVERAGE COLOR WHEN YOU EXPORT STLs TO
LITEMATICA
Ex: Gray Wool = minecraft:gray_wool, and its color is ~ 72, 72, 72. In the file it will be
    Gray Wool=minecraft:gray_wool=72,72,72

If no configuration file is found in this folder, the script will create a "default.conf"
file.

The different files here starting with "MC_x.y.z" contains ALL BLOCKS for this specific MC
version. You are free to add other blocks for mods, to create minimal lists if you want to
look for fewer names (ex: wool.conf, concrete.conf, stone.conf) or even for minecraft mods
(create_6.0.conf, aeronautics.conf, mahoutsukai.conf, or any mod you would like to do)

RULES TO CREATE A CUSTOM LIST
  1. The script only reads configuration files that ends with ".conf"
  2. The structure must be 1 block per line using the following format:
         "Block Name=minecraft:block_name=R,G,B"
  3. Avoid naming it "default.conf" since the script creates one by default

THEREFORE
If you want to disable a configuration list, name it with another extension. Let's say you
do not play Minecraft version 1.8.9, you can disable the configuration list by renaming it
from "MC_1.8.9.conf" to "MC_1.8.9.conf.bak" or any other extension that is not ".conf".

Have fun while creating these configuration files it's the worst part don't worry (submit
them as pull requests also !!!!!! thank you <3)

~ Spooooooooder Neko 
