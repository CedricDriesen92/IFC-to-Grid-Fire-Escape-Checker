# IFC-to-IFC-multilevel-A*-Pathfinder
How to run: launch app.py!

![IFCoutput](https://github.com/user-attachments/assets/ffbaa049-91d3-4f99-a91b-a2b46688e471)

The program works in three steps:
1) IFC to Grid
    IFC gets transformed into linked 2D grids per floor, with for now support for automatic wall/door/stair/floor detection and grid size options (ideal is any subdivision of .4 to match the Belgian law). Sample Duplex.ifc included, but should work with any file.
2) Live grid painting + updates
    Grid can be edited live using editing tools, if the transformation was not perfect. Hopefully very user friendly.
![Interface](https://github.com/user-attachments/assets/be89edff-774b-4d23-9345-2fac5fd75ae4)
3) Fast grid-to-graph for A* multi-goal multi-floor pathfinder
    For manual start/goal placement there are buttons to place them. Right click to remove a start/goal (make sure to really click the center, it uses the center grid point... Strongest feature is the detect exits & update spaces -> calculate all routes. This automatically detects the exits and finds all the separate spaces (including buffer), then for every space it calculates its furthest point to the closest exit, as well as the distance to the stair (if it's not on the same floor as the exit), which is then compared to the (for now simplified) Belgian law. The grid buffer is set to 0.4 m by default to check the 0.8 m minimum width for doors/escape routes. The routing is done using A*, where for efficiency the grid is transformed into a weighted graph format (to allow higher costs for entering a door for example, or taking into account the height of stairs).
![Escape routes](https://github.com/user-attachments/assets/127e4bb1-058d-4f4e-826f-797ae1bf8f08)
4) (Optional) The result can also be re-exported into the IFC as 3D geometry of the routes, split up by floor, with the metadata attached.
![IFC export visualized](https://github.com/user-attachments/assets/f31ebd99-1876-4905-acac-0d0333cb5664)

To do:
- Make able to call via command line, easy since everything is already automatic.
- Automatically create a validation report, incl figures/spaces that violate which rules/whatever is necessary for the designer.
- Try again to align spaces with the IfcSpace, but their geometry doesn't seem to line up correctly... Maybe mix calculating the spaces myself and extracting the IFC properties of its closest matching IfcSpace?
- Check for a visibility graph version, since for large IFC files with many rooms a grid pathfinder (esp with many floors) can be slow. Maybe a hybrid approach where the grid inside a space is transformed into a visibility graph, connected via doors, to be explored.
- Try to do something similar for point clouds / Gaussian Splats / NERF... But maybe less ambitious.
