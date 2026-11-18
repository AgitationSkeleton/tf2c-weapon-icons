# Credits

The icon tools were written from scratch. The weapons shown in the icons were designed and
modelled by other people, credited below. The icons are derived from their models with thanks.

## Open Fortress Team

Models used for the Merc kill icons: Crowbar, Lead Pipe, Knife, Chainsaw, Pistol, Akimbo Pistols,
Revolver, Tommy Gun, Dynamite, Super Shotgun, Assault Rifle, Rocket Launcher, Gatling Gun, Railgun,
Lightning Gun and BFG. The Chainsaw (Classic) bucket icon is posed like Open Fortress's chainsaw
icon.

**Open Fortress's kill-icon art, by BobbusMcGee.** Five kill icons trace Open Fortress's own
kill-feed icons (`d_images_of`), drawn for Open Fortress by **BobbusMcGee**, vectorised into the TF2 Classified style by `tools/killicons/ofref.py`: the
Grenade Launcher (`tf2cc_merc_chinalake_v2`), Quad Launcher, Bouncer, Eternal Shotgun and Saw
Ballista. The Lead Pipe, Knife and Chainsaw `_v2` icons are posed after Open Fortress's icons for
those weapons, and the BFG's burst takes the colour of Open Fortress's. Every Open
Fortress-derived icon was checked against Open Fortress's icon for the same weapon. Open
Fortress's sprites themselves are not included in this repository.

| Role | Credit |
|---|---|
| Programming | KayDemonLP |
| Modeller | Alaxe |
| Concept Artist | DrPyspy |
| Animators | Hex, Coolchou Zhao, Polybagel |
| Weapon Modellers | Mr. Big, Overpovered, DrPyspy |
| Combat Knife | scrunt |

## Team Fortress 2 Classic Team

Models from TF2 Classic 2.0.0 betas 2 and 4: Super Shotgun (beta 4), Chainsaw (Classic), Tommy
Gun (beta 4), Six-Shooter, Frag Grenade, Heavy Artillery, Sten Gun, Poacher's Pride, Scout's SMG,
Beta Cyclops and Beta R.P.G. Beta 2-4 content was made by the TF2 Classic team (Eminoma).

| Role | Credit |
|---|---|
| Modeller (weapons) | svdl |
| Modeller (Mercenary) | Maxxy |
| Concept Artist (Mercenary) | Blaholtzen |

The Frag Grenade ("c_peenade") is a TF2 Steam Workshop model that came into TF2 Classic. Its
authors are not named in any source we have; it is credited through TF2 Classic.

## TF2C Presplit / TDC Team (the 4dm / 4rdm maps)

Models from the weapon set packed into the 4dm/4rdm maps: Crowbar and Lead Pipe (old Merc), Sten
Gun and Coffee Pot. Credited per the maps' `credits.txt`: EonDynamo, Pretz, OneFourth, Stev, Rad,
Anreol and DrudlyClean, with the Open Fortress Team.

## TF2 Classified Team

* TF2 Classified build 5205: the game these icons are made for. Its stock death-notice icons were
  measured to derive the kill-icon style, and its stock item icons are used as camera and colour
  references for the bucket renders. None of its icons are included here.
* TF2 Classified April Fools 2026 pack (official 3.0.11 release): the Flyswatter.

## MarxVee pack

The Machine Gun and Medkit, from the MarxVee TF2 Custom Class pack. Some MarxVee-pack assets were
made by community members who aren't named in the pack. If you made one of them, please get in
touch so you can be credited.

## Valve

Team Fortress 2: the Rescue Ranger and the flamethrower model used as the Makeshift Mutilator,
both as ported in TF2 Classic 2.2.3. Source engine formats (MDL / VVD / VTX / VTF / VMT).

## Software

| Project | Use | Licence |
|---|---|---|
| [tf2c-customslop](https://github.com/AgitationSkeleton/tf2c-customslop) | v2 icon renderer (`render.py`, `iconfit.py`, `srcshade.py`, `vmrender.py`, `vfs.py`, `vtf.py`), imported at run time by the bucket tools; not bundled | GPL-3.0 |
| [tf2cc](https://github.com/AgitationSkeleton/tf2cc-tf2classified) | the custom weapons these icons were made for; `srcmodel.py` and `dxt.py` come from its development tree (the same `srcmodel.py` ships in tf2c-customslop) | GPL-3.0 |
| numpy, SciPy, Pillow | numerics, image processing | BSD / BSD / MIT-CMU |
