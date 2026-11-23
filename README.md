# IFC-to-IFC-multilevel-A*-Pathfinder
How to run: launch app.py!

![IFCoutput](https://github.com/user-attachments/assets/ffbaa049-91d3-4f99-a91b-a2b46688e471)

The program works in three steps:
1) IFC to Grid
    IFC gets transformed into linked 2D grids per floor, with for now support for automatic wall/door/stair/floor detection and grid size options (ideal is any subdivision of .4 to match the Belgian law). Sample Duplex.ifc included, but should work with any file.
2) Live grid painting + updates
    Grid can be edited live using editing tools, if the transformation was not perfect. Hopefully very user friendly.
![Interface](https://github.com/user-attachments/assets/be89edff-774b-4d23-9345-2fac5fd75ae4)
3) Grid to graph, exits, spaces and routes
    For manual start/goal placement there are buttons to place them (Find Path gives the shortest route over all floors). Right click to remove a start/goal. Strongest feature is Calculate ALL: it finds the exits and the spaces (the model's IfcSpaces, or regions detected on the grid), then for every space the point furthest from its nearest exit, and checks the distances against the Belgian basic standards for low buildings (see "How the checks work" below). The wall buffer is 0.4 m by default, so passages and doors narrower than 0.8 m are closed. The grid becomes a sparse weighted graph (stairs cost their walked 3D length; optionally doors cost extra) searched with scipy's Dijkstra.
![Escape routes](https://github.com/user-attachments/assets/127e4bb1-058d-4f4e-826f-797ae1bf8f08)
4) (Optional) The result can also be re-exported into the IFC as 3D geometry of the routes, per floor, with the metadata attached. Routes end at the exit of the person's floor (a stairwell on upper floors), as the regulation measures them.
![IFC export visualized](https://github.com/user-attachments/assets/f31ebd99-1876-4905-acac-0d0333cb5664)
5) (Optional) The result can also be exported as a PDF report.
![SampleReport](https://github.com/user-attachments/assets/a63c63a0-4384-4d81-bc65-c12518cb17ec)

How the checks work (KB 7 July 1994, annex 2/1, low buildings; medium and high buildings are not covered yet):
- Geometry: every wall, slab, door and stair (subtypes included, plus parts such as curtain wall panels) is triangulated with ifcopenshell's geometry iterator in world coordinates, and the triangles of each element mark the cells they cover in plan (scanline, so rotated walls stay thin). Floor heights come from each storey's world placement, so georeferenced models work. Elements without usable geometry are listed in the upload response (`warnings.skipped_elements`) and shown in the app.
- Spaces: the model's IfcSpaces by default (their footprints, with their names); floors without IfcSpaces fall back to regions detected on the grid, and the "Spaces" switch can use detected regions everywhere.
- Clear width: a wall buffer of N cells keeps passages and doors of at least 2N cells open (0.8 m for N = 4 at 0.1 m, the LG 4.4.1.1 minimum) and closes anything narrower, straight or diagonal.
- Exits (LG 4.4.1.2): on the evacuation level (the storey at ±0.00, annex 1, 5.6.8), door groups that lead outside: Pset_DoorCommon.IsExternal decides when the IFC fills it; otherwise a door counts when it has a clear line to the edge of the model. On every other floor, the stairs that reach an evacuation level (LG 4.2.2.2). Doors on upper floors (balconies) are never exits. Goals can still be placed by hand.
- Distances (LG 4.4.1.1): measured on the person's own floor to the access of the nearest exit; the way through the stairwell and in the open air does not count. One Dijkstra search from all exits (scipy, in C) gives every cell its distance, so each space is judged at its truly furthest cell; the distance to a second, different exit comes from one search per exit.
- Rules (`check_escape_route_rules`): nearest exit ≤ 45 m day / 30 m night; the number of exits from the occupancy (LG 2.2.1: 1 below 100 persons, 2 up to 499, 2 + n from 500); when two or more are needed (or "Require second exit" is ticked), the second exit ≤ 80 / 60 m. Results list what is not checked (`not_checked`): the 30 / 20 m to the evacuation route connecting the exits, dead ends of 15 m, the required width per occupant, protected evacuation routes and external stairs as exits, exits in opposite zones, compartments and parkings.
- Grids travel packed in the API (one character per cell, rows as strings; `grid_codec.py`), about 8 times smaller than nested lists of names, which are still accepted.

Tests: `python -m pytest tests` (the Duplex test needs `ExampleInputs/Duplex.ifc`).

To do:
- Make able to call via command line, easy since everything is already automatic.
- Include floor plans in the report.
- Check for a visibility graph version, since for large IFC files with many rooms a grid pathfinder (esp with many floors) can be slow. Maybe a hybrid approach where the grid inside a space is transformed into a visibility graph, connected via doors, to be explored.
- Try to do something similar for point clouds / Gaussian Splats / NERF... But maybe less ambitious.
