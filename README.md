# Editeable-IFC-multilevel-A-Pathfinder
How to run: launch app.py!

The program works in three steps:
1) IFC to Grid
    IFC gets transformed into linked 2D grids per floor, with for now support for automatic wall/door/stair/floor detection and grid size options (ideal is any subdivision of .4 to match the Belgian law). Sample Duplex.ifc included, but should work with any file.
2) Live grid painting + updates
    Grid can be edited live using editing tools, if the transformation was not perfect. Hopefully very user friendly, although it really needs a line tool.
3) Fast grid-to-graph for A* multi-goal multi-floor pathfinder
    For manual start/goal placement there are buttons to place them. Right click to remove a start/goal (make sure to really click the center, it uses the center grid point... Strongest feature is the detect exits & update spaces -> calculate all routes. This automatically detects the exits and finds all the separate spaces (including buffer), then for every space it calculates its furthest point to the closest exit, as well as the distance to the stair (if it's not on the same floor as the exit), which is then compared to the (for now simplified) Belgian law. The grid buffer is set to 0.4 m by default to check the 0.8 m minimum width for doors/escape routes. The routing is done using A*, where for efficiency the grid is transformed into a weighted graph format (to allow higher costs for entering a door for example, or taking into account the height of stairs).

To do:
- Make able to call via command line, easy since everything is already automatic.
- Automatically create a validation report, incl figures/spaces that violate which rules/whatever is necessary for the designer.
- Fix JSON import/export.
- Detect stairways for better length calculation, should be any space containing a stair (wall buffer taken into account), simple.
- Try again to align spaces with the IfcSpace, but their geometry doesn't seem to line up correctly... Maybe mix calculating the spaces myself and extracting the IFC properties of its closest matching IfcSpace?
- Create a line tool for painting...
- Give stairs connected to other floors a different hue, to indicate this.
- Make stairs not enterable from the sides! Taking longest side as the direction of the stair works mostly but not always, since the part of the stair on one floor can be small and create a wrong direction. Using the connection should work (find out which direction is connected all the way, then rotate 90 degrees to find stair direction), but could give issues with rotating stairs... Any indication from IFC we could import?
- Check for a visibility graph version, since for large IFC files with many rooms a grid pathfinder (esp with many floors) can be slow. Maybe a hybrid approach where the grid inside a space is transformed into a visibility graph, connected via doors, to be explored.
- Try to do something similar for point clouds / Gaussian Splats / NERF... But maybe less ambitious.
