                                  CONFIGURATION FOR BLOCKS
                                ============================

THIS FOLDER CONTAINS BLOCK NAMES AND ITS MINECRAFT NAME WHEN YOU EXPORT STLs TO LITEMATICA
Example: Dirt is "minecraft:Dirt", Shaft from create is "create:shaft"

If no configuration file is found in this folder, the script will create a "default.conf"
file.

The different files here starting with "MC_x.y.z" contains ALL BLOCKS for this specific MC
version. You are free to add other blocks for mods, to create minimal lists if you want to
look for fewer names (ex: wool.conf, concrete.conf, stone.conf) or even for minecraft mods
(create_6.0.conf, aeronautics.conf, mahoutsukai.conf, or any mod you would like to do)

RULES TO CREATE A CUSTOM LIST
  1. The script only reads configuration files that ends with ".conf"
  2. The structure inside must be per line the format "Block Name=minecraft:block_name"
     (corresponding to your blocks)
  3. Avoid naming it "default.conf" since the scripts creates one by default

THEREFORE
If you want to disable a configuration list, name it with another extension. Let's say you
do not play Minecraft version 1.8.9, you can disable the configuration list by renaming it
from "MC_1.8.9.conf" to "MC_1.8.9.conf.bak" or any other extension that is not ".conf".

Have fun while creating these configuration files it's the worst part don't worry (submit
them as pull requests also !!!!!! thank you <3)

~ Spooooooooder Neko 
