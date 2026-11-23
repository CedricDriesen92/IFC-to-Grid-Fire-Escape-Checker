# Escape Route Checker

Checks the escape routes in an IFC model against the Belgian fire-safety rules for low buildings (KB 7 July 1994,
annex 2/1). The model becomes a grid per floor that you can correct by hand. Every space is then checked for its
distance to the nearest exit, and to a second exit when one is needed. Results export as a PDF report (English,
Dutch or French), as routes in the IFC, or as a grid file.

Run it with `pip install -r requirements.txt` and `python app.py`, then open http://localhost:8000.

![IFCoutput](https://github.com/user-attachments/assets/ffbaa049-91d3-4f99-a91b-a2b46688e471)

## Using the app

The sidebar has four steps, and the results open on the right.

1. Model: load an `.ifc` (converted in the background) or a saved grid `.json`, with an optional mapping file (see
   below). Each model becomes a project that saves as you work, in `uploads/projects/`. Recent projects reopen from
   the list, and the page address reopens the same project after a reload.
2. Check the grid: paint walls, doors, stairs, floor or empty cells with the brush, line and fill tools, and undo with
   Ctrl+Z. Set the clear width (0.80 m is the LG minimum), place exits by hand, or find a path between two points.
3. Check the routes: choose IfcSpaces or detected spaces and a default occupancy, then run the checks.
4. Export the PDF report, the IFC with routes, or the grid file.

The results list each space with its status, use (day or night, editable), distance to the exit, kind of exit and
distance to a second exit. Click a space to see its route on the plan. A space without a route says why: no exit on
its floor, only reachable through a passage narrower than the clear width (the bottleneck is marked), or walled off.
The compartments section sets the occupancy per compartment, which decides the number of exits. The S/10 button
estimates it at one person per 10 m² (annex 1, 1.6.2).

The wheel zooms, and the middle or right mouse button pans. T switches to a 3D view, which loads three.js from a
CDN the first time. Press ? for all shortcuts.

## How the checks work

Only annex 2/1 (low buildings) is covered.

- Geometry: walls, slabs, doors and stairs, with their subtypes and parts, are triangulated in world coordinates and
  marked on the cells they cover. Doors follow their own orientation. Floor heights come from each storey's world
  placement, so georeferenced models work. The app reports elements without usable geometry.
- Spaces: IfcSpaces by default, with their names, use, occupancy and FireExit. "Night occupancy" in
  Pset_SpaceOccupancyRequirements.OccupancyType means night use and any other value day use, as in Rule Gen (D17).
  Without a value, a name such as "bedroom" suggests night use. Walkable area outside every IfcSpace is checked as
  extra regions, and floors without IfcSpaces use regions found on the grid.
- Compartments: IfcSpatialZones and IfcZones marked as fire compartments; otherwise each floor is one (LG 2.1).
  The occupancy set in the app comes first, then the zone's, then the sum of its spaces', then the default.
- Clear width: a buffer of N cells keeps passages and doors of 2N cells open (0.80 m for N = 4 at 0.1 m) and closes
  anything narrower.
- Exits (LG 4.4.1.2): doors to the outside on the evacuation level, the storey at ±0.00 (annex 1, 5.6.8). IsExternal
  decides when the IFC fills it, otherwise a clear line to the edge of the model. On other floors, stairs that reach
  the evacuation level (LG 4.2.2.2). FireExit spaces count too: a stairwell above or below the evacuation level, an
  evacuation route on it. So do FireExit doors next to them. Balcony doors never count.
- Distances (LG 4.4.1.1): measured on the person's own floor to the nearest exit. The way through the stairwell and
  in the open air does not count. Routes from the furthest cells are straightened to lines of sight, because grid
  steps overstate walked length by up to 8 %. Second-exit distances are still grid lengths.
- Rules: nearest exit within 45 m by day and 30 m by night, following each space's use (both when unknown). The
  number of exits follows the compartment's occupancy (LG 2.2.1): 1 below 100 persons, 2 up to 499, 2 + n from 500.
  When two or more are needed, the second exit must be within 80 m by day and 60 m by night.
- Not checked, and listed as such in the app and the report: the 30 / 20 m to the evacuation route, dead ends of
  15 m, width per occupant, external stairs and the fire resistance of protected routes, exits in opposite zones,
  and parkings.

## Element mapping

Some exports model floors or stairs as `IfcBuildingElementProxy`. A mapping file says what they are. The first rule
that matches the IFC class (subtypes included) and a regular expression on Name or ObjectType wins:

```json
{"rules": [
  {"class": "IfcBuildingElementProxy", "name": "laipt\\w* mar", "as": "stair", "flat_stair": true},
  {"class": "IfcBuildingElementProxy", "name": "perdangos plok|grindu apdaila", "as": "floor"},
  {"class": "IfcFurnishingElement", "as": "ignore"}
]}
```

`as` is `stair`, `floor`, `wall`, `door` or `ignore`. With `flat_stair`, a flat stair symbol at floor level rises
to the next level where another flight starts. See `mappings/archicad-lithuanian-proxies.json`.

## API

Projects keep their state on the server. `POST /api/projects` takes an IFC (returns a job to poll at
`GET /api/jobs/<id>`) or a grid file. The project routes are `GET /api/projects/<id>` and `POST .../edit`,
`.../undo`, `.../settings`, `.../floors`, `.../exits`, `.../overrides`, `.../ifc`, `.../analyse` and `.../path`, plus
`GET .../export/{pdf,ifc,grid}`. The older stateless routes such as `/api/process-file` still work. Grids travel
packed, one character per cell (`grid_codec.py`), or as nested names.

Tests: `python -m pytest tests`. The Duplex test needs `ExampleInputs/Duplex.ifc`.

## To do

- Command-line mode for batch checks, reference results per example model, BCF export of violations.
- Floor plans with routes in the PDF report.
- Medium and high buildings (annexes 3/1 and 4/1), dead ends, distance to the evacuation route, width per occupant.
- Something similar for point clouds, Gaussian splats or NeRF.
