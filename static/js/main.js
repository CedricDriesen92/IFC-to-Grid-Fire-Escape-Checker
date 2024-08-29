// State variables
let originalGridData = null;
let bufferedGridData = null;
let currentFloor = 0;
let currentFloorElevation = 0;
let floorElevations = null;
let currentType = 'wall';
let currentTool = 'paint';
let start = null;
let goals = [];
let cellSize = 20;
let isPainting = false;
let minZoom = 1;
let zoomLevel = 50000;
let brushSize = 1;
let lastPaintedCell = null;
let lastPreviewCell = null;
let isDrawingLine = false;
let lineStart = null;
let previewCells = new Set();
let isMouseDown = false;
let wallBuffer = 4;
let paintedCells = new Set();
let pathfindingSteps = [];
let currentStepIndex = 0;
let animationInterval = null;
let pathData = null;
let allowDiagonal = true;
let minimizeCost = false;
let spacesData = [];
let includeEmptyTiles = false;
let foundEscapeRoutes = null;
let spaceColors = {};
let maxStairDistance = 30;
let isDragging = false;
let lastMouseX, lastMouseY;
let zoomFactor = 1;
let panX = 0;
let panY = 0;
let transform = new DOMMatrix();
let inverseTransform = new DOMMatrix();
let showBuffer = false;
let showSpaces = true;
let cellBufferScale = 100;
let stairConnections = null;
let file = null;
let isIFC = null;
let ifcExists = false;
let global_ifc_file = null;

const MAX_TRAVEL_DISTANCES = {
    daytime: {
        toEvacRoute: 30,
        toNearestExit: 45,
        toSecondExit: 80
    },
    nighttime: {
        toEvacRoute: 10,//20,
        toNearestExit: 15,//30,
        toSecondExit: 60
    }
};
const MAX_DEAD_END_LENGTH = 15;
const MIN_WIDTHS = {
    evacuationRoute: 0.8,
    door: 0.8,
    escapeTerrace: 0.6
};
const MIN_STAIRWAY_WIDTH = 0.8;
const MIN_STAIRWAY_DISTANCE = 10;
const MAX_STAIRWAY_DISTANCE = 60;

// DOM elements
const gridContainer = document.getElementById('grid-container');
const canvas = gridContainer.querySelector('canvas');
const progressContainer = document.getElementById('progress-container');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const fileUploadForm = document.getElementById('file-upload-form');
const zoomSlider = document.getElementById('zoom-slider');
const brushSizeSlider = document.getElementById('brush-size');
const wallBufferSlider = document.getElementById('wall-buffer');
document.getElementById('wall-buffer-display').textContent = '0.4';
wallBufferSlider.value = 4;
const allowDiagonalCheckbox = document.getElementById('allow-diagonal');
const minimizeCostCheckbox = document.getElementById('minimize-cost');
//const updateIfcForm = document.getElementById('update-ifc-form');
const detectExitsButton = document.getElementById('detect-exits');
const spaceDetectionButton = document.getElementById('update-spaces');
const maxStairDistanceSlider = document.getElementById('max-stair-distance');
const maxStairDistanceDisplay = document.getElementById('max-stair-distance-display');
const outputText = document.getElementById('result');
const showBufferCheckbox = document.getElementById('show-buffer');
const showSpacesCheckbox = document.getElementById('show-spaces');

// Event listeners
fileUploadForm.addEventListener('submit', uploadFile);
zoomSlider.addEventListener('input', handleZoomChange);
brushSizeSlider.addEventListener('input', handleBrushSizeChange);
wallBufferSlider.addEventListener('input', handleWallBufferChange);
gridContainer.addEventListener('mousedown', handleMouseDown);
gridContainer.addEventListener('mousemove', handleMouseMove);
gridContainer.addEventListener('mouseup', handleMouseUp);
gridContainer.addEventListener('mouseleave', handleMouseLeave);
gridContainer.addEventListener('mousemove', handleGridHover);
gridContainer.addEventListener('mouseout', handleGridMouseOut);
allowDiagonalCheckbox.addEventListener('change', (e) => {
allowDiagonal = e.target.checked;
});
minimizeCostCheckbox.addEventListener('change', (e) => {
    minimizeCost = e.target.checked;
});
//updateIfcForm.addEventListener('submit', updateIfcWithRoutes);
gridContainer.addEventListener('contextmenu', (e) => e.preventDefault());
detectExitsButton.addEventListener('click', detectExits);
document.getElementById('include-empty-tiles').addEventListener('change', (e) => {
    includeEmptyTiles = e.target.checked;
});
spaceDetectionButton.addEventListener('click', updateSpaces);
maxStairDistanceSlider.addEventListener('input', handleMaxStairDistanceChange);
gridContainer.addEventListener('wheel', handleWheel);
showBufferCheckbox.addEventListener('change', (e) => {
    showBuffer = e.target.checked;
    renderGrid(bufferedGridData.grids[currentFloor]);
});
showSpacesCheckbox.addEventListener('change', (e) => {
    showSpaces = e.target.checked;
    renderGrid(bufferedGridData.grids[currentFloor]);
});
spaceDetectionButton.addEventListener('click', () => {
    updateSpaces().catch(error => {
        showError(`An error occurred while updating spaces: ${error.message}`);
    });
});

document.getElementById('paint-tool').addEventListener('click', () => setCurrentTool('paint'));
document.getElementById('line-tool').addEventListener('click', () => setCurrentTool('line'));
document.getElementById('fill-tool').addEventListener('click', () => setCurrentTool('fill'));
document.getElementById('draw-wall').addEventListener('click', () => setCurrentType('wall', 'paint'));
document.getElementById('draw-door').addEventListener('click', () => setCurrentType('door', 'paint'));
document.getElementById('draw-stair').addEventListener('click', () => setCurrentType('stair', 'paint'));
document.getElementById('draw-floor').addEventListener('click', () => setCurrentType('floor', 'paint'));
document.getElementById('draw-empty').addEventListener('click', () => setCurrentType('empty', 'paint'));
document.getElementById('line-wall').addEventListener('click', () => setCurrentType('wall', 'line'));
document.getElementById('line-door').addEventListener('click', () => setCurrentType('door', 'line'));
document.getElementById('line-stair').addEventListener('click', () => setCurrentType('stair', 'line'));
document.getElementById('line-floor').addEventListener('click', () => setCurrentType('floor', 'line'));
document.getElementById('line-empty').addEventListener('click', () => setCurrentType('empty', 'line'));
document.getElementById('fill-wall').addEventListener('click', () => setCurrentType('wall', 'fill'));
document.getElementById('fill-door').addEventListener('click', () => setCurrentType('door', 'fill'));
document.getElementById('fill-stair').addEventListener('click', () => setCurrentType('stair', 'fill'));
document.getElementById('fill-floor').addEventListener('click', () => setCurrentType('floor', 'fill'));
document.getElementById('fill-empty').addEventListener('click', () => setCurrentType('empty', 'fill'));

document.getElementById('prev-floor').addEventListener('click', navigateToPreviousFloor);
document.getElementById('next-floor').addEventListener('click', navigateToNextFloor);
document.getElementById('clear-floor').addEventListener('click', clearCurrentFloor);
document.getElementById('add-floor').addEventListener('click', addNewFloor);
document.getElementById('remove-floor').addEventListener('click', removeCurrentFloor);
document.getElementById('set-start').addEventListener('click', () => setCurrentType('start'));
document.getElementById('set-goal').addEventListener('click', () => setCurrentType('goal'));
document.getElementById('find-path').addEventListener('click', findPath);
//document.getElementById('download-grid').addEventListener('click', downloadGrid);
document.getElementById('calculate-escape-routes').addEventListener('click', calculateEscapeRoutes);
document.getElementById('export-grid').addEventListener('click', exportGrid);
document.getElementById('update-ifc-button').addEventListener('click', updateIfcWithRoutes);
document.getElementById('export-pdf-button').addEventListener('click', exportPdfReport);

function initializeToolMenus() {
    const paintTool = document.getElementById('paint-tool');
    const lineTool = document.getElementById('line-tool');
    const fillTool = document.getElementById('fill-tool');
    const paintMenu = document.getElementById('paint-menu');
    const lineMenu = document.getElementById('line-menu');
    const fillMenu = document.getElementById('fill-menu');

    if (!paintTool || !lineTool || !fillTool || !paintMenu || !lineMenu || !fillMenu) {
        console.error('One or more tool elements not found');
        return;
    }

    function showMenu(menu) {
        menu.classList.remove('hidden');
    }

    function hideMenu(menu) {
        menu.classList.add('hidden');
    }

    paintTool.addEventListener('mouseenter', () => showMenu(paintMenu));
    paintTool.addEventListener('mouseleave', () => {
        setTimeout(() => {
            if (!paintMenu.matches(':hover')) {
                hideMenu(paintMenu);
            }
        }, 100);
    });
    paintMenu.addEventListener('mouseleave', () => hideMenu(paintMenu));

    lineTool.addEventListener('mouseenter', () => showMenu(lineMenu));
    lineTool.addEventListener('mouseleave', () => {
        setTimeout(() => {
            if (!lineMenu.matches(':hover')) {
                hideMenu(lineMenu);
            }
        }, 100);
    });
    lineMenu.addEventListener('mouseleave', () => hideMenu(lineMenu));

    fillTool.addEventListener('mouseenter', () => showMenu(fillMenu));
    fillTool.addEventListener('mouseleave', () => {
        setTimeout(() => {
            if (!fillMenu.matches(':hover')) {
                hideMenu(fillMenu);
            }
        }, 100);
    });
    fillMenu.addEventListener('mouseleave', () => hideMenu(fillMenu));
    console.log("Tools init");
}

async function uploadFile(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    file = formData.get('file');

    showProgress('Initializing...');

    try {
        let result;
        if (file.name.toLowerCase().endsWith('.json')) {
            isIFC = false;
            // Handle JSON file
            const fileContent = await file.text();
            result = JSON.parse(fileContent);
            handleProcessedData(result);
        } else {
            isIFC = true;
            // Handle IFC file
            const response = await fetch('/api/process-file', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

            result = await response.json();
            handleProcessedData(result);
        }

        console.log('Received data:', result);
    } catch (error) {
        console.error('Error:', error);
        showError('An error occurred while processing the file.');
    } finally {
        hideProgress();
    }
}

async function checkIfcFileExists(fileName) {
    try {
        const response = await fetch('/api/check-ifc-file', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ fileName: fileName })
        });
        const data = await response.json();
        return data.exists;
    } catch (error) {
        console.error('Error checking IFC file existence:', error);
        return false;
    }
}

function exportGrid() {
    if (!originalGridData) {
        showError('No grid data available. Please upload or create a grid first.');
        return;
    }

    const dataToSave = {
        grids: originalGridData.grids,
        grid_size: originalGridData.grid_size,
        floors: originalGridData.floors,
        bbox: originalGridData.bbox,
        unit_size: originalGridData.unit_size,
        original_ifc_filename: file ? file.name : null
    };

    const jsonString = JSON.stringify(dataToSave, null, 2);
    const blob = new Blob([jsonString], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const downloadLink = document.createElement('a');
    downloadLink.href = url;
    
    // Use the original IFC filename if available, otherwise use a default name
    const originalFilename = fileUploadForm.querySelector('input[type="file"]').files[0]?.name;
    downloadLink.download = originalFilename ? originalFilename.replace('.ifc', '_edited.json') : 'edited_grid.json';

    document.body.appendChild(downloadLink);
    downloadLink.click();
    document.body.removeChild(downloadLink);

    URL.revokeObjectURL(url);
}

function handleProcessedData(data) {
    originalGridData = data;
    bufferedGridData = {...data};
    console.log(originalGridData.floors);
    
    if (typeof originalGridData.grid_size === 'number') {
        originalGridData.grid_size *= originalGridData.unit_size || 1;
        bufferedGridData.grid_size *= bufferedGridData.unit_size || 1;
        console.log('Adjusted grid size:', bufferedGridData.grid_size);
    } else {
        console.error('Invalid grid_size in loaded data:', originalGridData.grid_size);
        showError('Invalid grid size in loaded data');
        return;
    }

    if (!Array.isArray(originalGridData.grids) || originalGridData.grids.length === 0) {
        console.error('Invalid grids data in loaded file:', originalGridData.grids);
        showError('Invalid grids data in loaded file');
        return;
    }

    console.log('Grid data seems valid, initializing grid...');
    initializeGrid();
    initializeToolMenus();
    // Check if an IFC file is linked
    if (!isIFC) {
        document.getElementById('ifc-file-input').style.display = 'block';
    } else {
        document.getElementById('ifc-file-input').style.display = 'none';
    }
    document.getElementById('update-ifc-button').style.display = 'none';
    document.getElementById('export-pdf-button').style.display = 'none';
}

async function initializeGrid() {
    console.log('Initializing grid...');
    const containerWidth = gridContainer.clientWidth;
    const containerHeight = gridContainer.clientHeight;
    console.log('Container dimensions:', containerWidth, containerHeight);

    if (!bufferedGridData || !bufferedGridData.grids || bufferedGridData.grids.length === 0) {
        console.error('Buffered grid data is not properly initialized');
        showError('Error initializing grid data. Please try refreshing the page.');
        return;
    }

    const gridWidth = bufferedGridData.grids[0][0].length;
    const gridHeight = bufferedGridData.grids[0].length;
    console.log('Grid dimensions:', gridWidth, gridHeight);

    const horizontalZoom = containerWidth / gridWidth;
    const verticalZoom = containerHeight / gridHeight;
    minZoom = Math.min(horizontalZoom, verticalZoom);
    console.log('Calculated zoom levels:', horizontalZoom, verticalZoom, minZoom);

    zoomLevel = 10*Math.max(100, Math.min(25000, Math.round(minZoom * 100)));
    cellSize = (zoomLevel / cellBufferScale) * bufferedGridData.grid_size;
    console.log('Set zoom level and cell size:', zoomLevel, cellSize);

    zoomSlider.value = zoomLevel;
    document.getElementById('hidden1').hidden = false;
    document.getElementById('hidden2').hidden = false;
    updateZoomLevel();
    await applyWallBuffer().then(() => {
        console.log('Initial wall buffer applied');
    }).catch(error => {
        console.error('Error applying initial wall buffer:', error);
        showError('An error occurred while applying the initial wall buffer. Please try again.');
    });
    await createOrFetchGraph();
    await getStairConnections();
    renderGrid(bufferedGridData.grids[currentFloor]);
    updateFloorDisplay();
}

function drawGridBorders(width, height, cellSize, ctx) {
    ctx.beginPath();
    
    // Vertical lines
    for (let x = 0; x <= width; x += cellSize) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
    }

    // Horizontal lines
    for (let y = 0; y <= height; y += cellSize) {
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
    }

    // Outer border
    ctx.rect(0, 0, width, height);

    ctx.strokeStyle = "grey";
    ctx.lineWidth = 0.5;
    ctx.stroke();
}

function renderGrid(grid) {
    gridContainer.innerHTML = '';
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    canvas.width = grid[0].length * cellSize;
    canvas.height = grid.length * cellSize;

    // Render the base grid
    grid.forEach((row, i) => {
        row.forEach((cell, j) => {
            ctx.fillStyle = getCellColor(cell);//mixHexes(getCellColor(cell), getCellColor(originalGridData.grids[currentFloor][i][j]), 0.7);
            if(cell == 'walla' && !showBuffer){
                ctx.fillStyle = getCellColor(originalGridData.grids[currentFloor][i][j]);
            }
            ctx.fillRect(j * cellSize, i * cellSize, cellSize, cellSize);
        });
    });

    drawGridBorders(canvas.width, canvas.height, cellSize, ctx);

    // Render spaces
    if(showSpaces){
        renderSpaces(ctx);
        //renderStairConnections(ctx);
    }


    // Render path if it exists
    if (pathData && !foundEscapeRoutes) {
        //console.log(pathData);
        ctx.fillStyle = 'rgba(255, 255, 0, 0.5)';
        pathData.forEach(point => {
            if (point[2] === currentFloor) {
                ctx.fillRect(point[1] * cellSize, point[0] * cellSize, cellSize, cellSize);
            }
        });
    }

    if (foundEscapeRoutes && foundEscapeRoutes.length >= 1) {
        //console.log(foundEscapeRoutes);
        let totalLength = 0;
        let stairwayDistance = -1;
        let spacesOverMaxDistance = [];
        let spacesWithoutExits = [];
        foundEscapeRoutes.forEach(route => {
            let hasViolations = false;
            if (route.distance){
                totalLength = Math.max(totalLength, route.distance);
                stairwayDistance = Math.max(stairwayDistance, route.distance_to_stair);
                const isOverMaxDistance = route.distance_to_stair > maxStairDistance || route.distance > maxStairDistance;
                if (isOverMaxDistance && route.distance_to_stair > maxStairDistance){
                    spacesOverMaxDistance.push(route.space_name);
                    outputText.innerHTML.concat("\nSpace: ", route.space_name, "\nDistance to stairway too long: ", route.distance_to_stair, "\nTotal route length: ", route.distance);
                }
                else if(isOverMaxDistance){
                    spacesOverMaxDistance.push(route.space_name);
                    outputText.innerHTML.concat("\nSpace: ", route.space_name, "\nDistance to closest escape is too long: ", route.distance);
                }
                if (route && route.violations && (route.violations['daytime'].length > 0 || route.violations['nighttime'].length > 0)) {
                    hasViolations = true;
                    ctx.setLineDash([5, 5]);
                } else {
                    ctx.setLineDash([]);
                }

                let curdist = 0;
                for (let i = 1; i < route.optimal_path.length; i++) {
                    const prevPoint = route.optimal_path[i - 1];
                    const currentPoint = route.optimal_path[i];

                    if (prevPoint[2] === currentFloor && currentPoint[2] === currentFloor) {
                        const [y1, x1] = prevPoint;
                        const [y2, x2] = currentPoint;
                        
                        const segmentDist = Math.sqrt((x2-x1)**2 + (y2-y1)**2) * bufferedGridData.grid_size;
                        curdist += segmentDist;

                        ctx.beginPath();
                        ctx.moveTo((x1 + 0.5) * cellSize, (y1 + 0.5) * cellSize);
                        ctx.lineTo((x2 + 0.5) * cellSize, (y2 + 0.5) * cellSize);

                        if (curdist > route.distance_to_stair) {
                            ctx.strokeStyle = hasViolations ? 
                                (route.violations['daytime'].length === 0 ? 'rgba(255, 165, 0, 1)' : 'rgba(255, 0, 0, 1)') :
                                'rgba(0, 255, 0, 1)';
                        } else {
                            ctx.strokeStyle = hasViolations ? 
                                (route.violations['daytime'].length === 0 ? 'rgba(210, 135, 0, 1)' : 'rgba(210, 0, 0, 1)') :
                                'rgba(0, 210, 0, 1)';
                        }

                        ctx.stroke();
                    }
                }

                route.optimal_path.forEach((point, index) => {
                    if (point[2] === currentFloor) {
                        const x = (point[1] + 0.5) * cellSize;
                        const y = (point[0] + 0.5) * cellSize;
                        const prevPoint = index > 0 ? route.optimal_path[index - 1] : null;
                        const nextPoint = index < route.optimal_path.length - 1 ? route.optimal_path[index + 1] : null;
                
                        if (prevPoint && prevPoint[2] !== currentFloor) {
                            const prevx = (prevPoint[1] + 0.5) * cellSize;
                            const prevy = (prevPoint[0] + 0.5) * cellSize;
                            const angle = Math.atan2(y - prevy, x - prevx) + Math.PI;
                            
                            ctx.fillStyle = 'rgba(0, 0, 255, 1)'; // Coming down (blue)
                            ctx.beginPath();
                            ctx.moveTo(prevx-cellSize/2, prevy);
                            ctx.lineTo(prevx+cellSize/2, prevy);
                            ctx.lineTo(prevx, prevy-cellSize);
                            ctx.closePath;
                            ctx.fill();
                            ctx.setLineDash([1,5]);
                            //ctx.strokeStyle = ctx.fillStyle;
                            ctx.lineWidth = 2;
                            ctx.moveTo(x, y);
                            ctx.lineTo(prevx, prevy);
                            ctx.stroke();
                        }
                
                        if (nextPoint && nextPoint[2] !== currentFloor) {
                            const nextx = (nextPoint[1] + 0.5) * cellSize;
                            const nexty = (nextPoint[0] + 0.5) * cellSize;
                            const angle = Math.atan2(nexty - y, nextx - x);
                            
                            ctx.fillStyle = 'rgba(255, 0, 255, 1)'; // Going up (pink)
                            ctx.beginPath();
                            ctx.moveTo(nextx-cellSize/2, nexty);
                            ctx.lineTo(nextx+cellSize/2, nexty);
                            ctx.lineTo(nextx, nexty+cellSize);
                            ctx.closePath;
                            ctx.fill();
                            ctx.setLineDash([1,5]);
                            //ctx.strokeStyle = ctx.fillStyle;
                            ctx.lineWidth = 2;
                            ctx.moveTo(x, y);
                            ctx.lineTo(nextx, nexty);
                            ctx.stroke();
                        }
                    }
                });

                // Mark the furthest point
                const furthestPoint = route.furthest_point;
                if (furthestPoint[2] === currentFloor) {
                    ctx.fillStyle = 'purple';
                    const x = (furthestPoint[1] + 0.5) * cellSize;
                    const y = (furthestPoint[0] + 0.5) * cellSize;
                    ctx.beginPath();
                    ctx.arc(x, y, cellSize * 1.5, 0, 2 * Math.PI);
                    ctx.fill();
                }
            }
            else{
                spacesWithoutExits.push(route.space_name);
            }
        });
        const pathLengthsElement = document.getElementById('path-lengths');
        pathLengthsElement.innerHTML = `
            <h3>Escape routes calculated:</h3>
            <p>Spaces over max stair distance: ${spacesOverMaxDistance.join(', ') || 'None'}</p>
            <p>Spaces with NO escape route: ${spacesWithoutExits.join(', ') || 'None'}</p>
        `;
    }


    // Render start point if it exists and is on the current floor
    if (start && start.floor === currentFloor) {
        ctx.fillStyle = 'green';
        ctx.beginPath();
        ctx.arc((start.col + 0.5) * cellSize, (start.row + 0.5) * cellSize, cellSize * 1.5, 0, 2 * Math.PI);
        ctx.fill();
    }

    // Render goal points if they exist and are on the current floor
    if (goals.length > 0) {
        ctx.fillStyle = 'red';
        goals.forEach(goal => {
            if (goal.floor === currentFloor) {
                ctx.beginPath();
                ctx.arc((goal.col + 0.5) * cellSize, (goal.row + 0.5) * cellSize, cellSize * 1.5, 0, 2 * Math.PI);
                ctx.fill();
            }
        });
    }

    gridContainer.appendChild(canvas);
    updateCanvasPosition();
}

function updateCanvasPosition() {
    const canvas = gridContainer.querySelector('canvas');
    if (canvas) {
        canvas.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomLevel / 10000})`;
    }
}

function renderSpaces(ctx) {
    const currentFloorSpaces = spacesData.filter(space => space.floor === currentFloor);

    //console.log('Rendering spaces for floor:', currentFloor, ' number: ', currentFloorSpaces.length);
    
    currentFloorSpaces.forEach((space, index) => {
        if (!spaceColors[space.id]) {
            spaceColors[space.id] = generateRandomColor();
        }
        let hasViolations = false;
        if (foundEscapeRoutes) {
            const route = foundEscapeRoutes.find(r => r.space_name === space.name);
            if (route && route.violations && (route.violations['daytime'].length > 0 || route.violations['nighttime'].length > 0)) {
                hasViolations = true;
            }
        }

        ctx.strokeStyle = hasViolations ? 'rgba(255, 0, 0, 0.1)' : 'rgba(0, 0, 0, 0.1)';
        ctx.lineWidth = hasViolations ? 3 : 2;
        ctx.fillStyle = spaceColors[space.id];
        if (!space.polygon || space.polygon.length === 0) {
            console.warn(`Space ${space.id} has no polygon`);
            return;
        }

        ctx.beginPath();
        space.polygon.forEach((point, i) => {
            const x = ((point[0] - bufferedGridData.bbox.min_x) / bufferedGridData.grid_size + 0.5) * cellSize;
            const y = ((point[1] - bufferedGridData.bbox.min_y) / bufferedGridData.grid_size + 0.5) * cellSize;
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Render space name and path lengths
        ctx.fillStyle = 'rgba(255, 255, 255, 1)';
        ctx.strokeStyle = 'rgba(0, 0, 0, 1)';
        ctx.lineWidth = 3;
        ctx.lineJoin="miter";
        ctx.font = 'bold 24px Arial';
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const centerX = space.polygon.reduce((sum, p) => sum + p[0], 0) / space.polygon.length;
        const centerY = space.polygon.reduce((sum, p) => sum + p[1], 0) / space.polygon.length;
        const textX = ((centerX - bufferedGridData.bbox.min_x) / bufferedGridData.grid_size + 0.5) * cellSize;
        const textY = ((centerY - bufferedGridData.bbox.min_y) / bufferedGridData.grid_size + 0.5) * cellSize;
        ctx.strokeText(space.name, textX, textY-25);
        ctx.fillText(space.name, textX, textY-25);
        ctx.font = '18px Arial';
        
        if (foundEscapeRoutes) {
            //foundEscapeRoutes.forEach(r=>console.log(r.space_name, " ", space.name));
            const route = foundEscapeRoutes.find(r => r.space_name === space.name);
            if (route && route.distance) {
                ctx.strokeText(`Total: ${route.distance.toFixed(2)}m`, textX, textY);
                ctx.fillText(`Total: ${route.distance.toFixed(2)}m`, textX, textY);
                if(route.distance_to_stair >= 0){
                    ctx.strokeText(`To Stairway: ${route.distance_to_stair.toFixed(2)}m`, textX, textY + 25);
                    ctx.fillText(`To Stairway: ${route.distance_to_stair.toFixed(2)}m`, textX, textY + 25);
                }
            }
            else if(route){
                //ctx.fillStyle = 'rgba(0, 0, 0, 1)';
                ctx.strokeText('NO ESCAPE ROUTE FOUND!', textX, textY);
                ctx.fillText('NO ESCAPE ROUTE FOUND!', textX, textY);
            }    
            else{
                ctx.strokeText('Waiting for result...', textX, textY);
                ctx.fillText('Waiting for result...', textX, textY);
            }
        }
    });
}

async function getStairConnections() {
    try {
        const response = await fetch('/api/get-stair-connections', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                floor: currentFloor
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const connections = await response.json();
        //console.log(connections);
        stairConnections = connections;
    } catch (error) {
        console.error('Error fetching stair connections:', error);
    }
}

function renderStairConnections(ctx) {
    try {
        const connections = stairConnections;
        //console.log(stairConnections);

        connections.forEach(conn => {
            const [y1, x1, floor1] = conn.start;
            const [y2, x2, floor2] = conn.end;

            //console.log(currentFloor, floor1, floor2);

            if (floor1 === currentFloor || floor2 === currentFloor) {
                // Use the same coordinate transformation as other elements
                const startX = (x1 + 0.5) * cellSize;
                const startY = (y1 + 0.5) * cellSize;
                const endX = (x2 + 0.5) * cellSize;
                const endY = (y2 + 0.5) * cellSize;

                ctx.beginPath();
                if (Math.abs(startX - endX) < cellSize && Math.abs(startY - endY) < cellSize) {
                    // Zero or very short distance connection
                    ctx.arc(startX, startY, cellSize / 2, 0, 2 * Math.PI);
                    ctx.fillStyle = floor2 > floor1 ? 'rgba(0, 0, 255, 0.5)' : 'rgba(255, 0, 255, 0.5)';
                    ctx.fill();
                } else {
                    ctx.moveTo(startX, startY);
                    ctx.lineTo(endX, endY);
                    ctx.strokeStyle = 'rgba(0, 0, 255, 0.5)';
                    if (floor1 >> currentFloor || floor2 >> currentFloor){
                        ctx.strokeStyle = 'rgba(255, 0, 255, 0.5)';
                    }
                    ctx.lineWidth = 2;
                    ctx.stroke();
                }
            } else {
                //console.log(`Connection not on current floor (${currentFloor}), skipping`);
            }
        });
    } catch (error) {
        console.error('Error in renderStairConnections:', error);
        console.error('Error details:', error.message);
        console.error('Stack trace:', error.stack);
    }
}

async function updateSpaces() {
    try {
        const response = await fetch('/api/update-spaces', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                include_empty_tiles: includeEmptyTiles,
                grids: bufferedGridData.grids,
                grid_size: bufferedGridData.grid_size,
                floors: bufferedGridData.floors,
                bbox: bufferedGridData.bbox,
            })
        });
        const data = await response.json();
        if (response.ok) {
            spacesData = data.spaces;
            renderGrid(bufferedGridData.grids[currentFloor]);
        } else {
            throw new Error(data.error || 'An error occurred while updating spaces.');
        }
    } catch (error) {
        console.error('Error:', error);
        throw error;
    }
}

function getCellColor(cellType) {
    const colors = {
        'wall': '#0e0e0e',
        'door': '#755e5a',
        'stair': '#e1c169',
        'floor': '#e5d1e5',
        'walla': '#92a0a0',
        'empty': '#ffffff'
    };
    return colors[cellType] || '#ffffff';
}

function hex2dec(hex) {
    const matched = hex.replace('#', '').match(/.{2}/g)
    if (!matched) throw new Error('Invalid hex string');
    return matched.map(n => parseInt(n, 16));
}

function rgb2hex(r, g, b) {
    r = Math.round(r);
    g = Math.round(g);
    b = Math.round(b);
    r = Math.min(r, 255);
    g = Math.min(g, 255);
    b = Math.min(b, 255);
    return '#' + [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('');
}

function mixHexes(hex1, hex2, ratio = 0.5) {
    if (ratio > 1 || ratio < 0) throw new Error('Invalid ratio');
    const [r1, g1, b1] = hex2dec(hex1);
    const [r2, g2, b2] = hex2dec(hex2);
    const r = Math.round(r1 * ratio + r2 * (1 - ratio));
    const g = Math.round(g1 * ratio + g2 * (1 - ratio));
    const b = Math.round(b1 * ratio + b2 * (1 - ratio));
    return rgb2hex(r, g, b);
}

function handleMouseDown(e) {
    const { row, col } = getCellCoordinates(e);
    
    if (e.button === 2) { // Right mouse button
        if (start && start.row === row && start.col === col && start.floor === currentFloor) {
            start = null;
            renderGrid(bufferedGridData.grids[currentFloor]);
        } else if (goals.some(goal => goal.row === row && goal.col === col && goal.floor === currentFloor)) {
            goals = goals.filter(goal => !(goal.row === row && goal.col === col && goal.floor === currentFloor));
            renderGrid(bufferedGridData.grids[currentFloor]);
        } else {
            isDragging = true;
            lastMouseX = e.clientX;
            lastMouseY = e.clientY;
        }
        e.preventDefault();
    } else if (e.button === 0) { // Left mouse button
        if (currentTool === 'line') {
            isDrawingLine = true;
            lineStart = { row, col };
        } else if (currentType === 'start') {
            start = { floor: currentFloor, row, col };
            renderGrid(bufferedGridData.grids[currentFloor]);
        } else if (currentType === 'goal') {
            goals.push({ floor: currentFloor, row, col });
            renderGrid(bufferedGridData.grids[currentFloor]);
        } else {
            startPainting(row, col);
        }
    }
}

function handleMouseMove(e) {
    if (isDragging) {
        const dx = e.clientX - lastMouseX;
        const dy = e.clientY - lastMouseY;
        panX += dx;
        panY += dy;
        updateCanvasPosition();
        lastMouseX = e.clientX;
        lastMouseY = e.clientY;
    } else {
        const { row, col } = getCellCoordinates(e);
        if (currentTool === 'line' && isDrawingLine) {
            renderGrid(bufferedGridData.grids[currentFloor]);
            previewLine(lineStart.row, lineStart.col, row, col);
        } else if (isMouseDown) {
            paint(row, col);
        } else {
            showPreview(row, col);
        }
    }
}

function handleMouseUp(e) {
    if (e.button === 2) {
        isDragging = false;
    } else if (e.button === 0) {
        if (currentTool === 'line' && isDrawingLine) {
            const { row, col } = getCellCoordinates(e);
            drawLine(lineStart.row, lineStart.col, row, col);
            isDrawingLine = false;
            lineStart = null;
        } else {
            stopPainting();
        }
    }
}

function handleMouseLeave(e) {
    if (e.button === 2) {
        isDragging = false;
    } else if (e.button === 0) {
        stopPainting();
    }
}

function handleWheel(e) {
    e.preventDefault();
    const delta = e.deltaY;
    const zoomSpeed = 0.1;
    
    const oldZoom = zoomLevel;
    if (delta > 0) {
        zoomLevel = Math.max(100, zoomLevel - zoomLevel * zoomSpeed);
    } else {
        zoomLevel = Math.min(25000, zoomLevel + zoomLevel * zoomSpeed);
    }

    const zoomFactor = zoomLevel / oldZoom;

    const rect = gridContainer.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Adjust pan to zoom from cursor position
    panX = mouseX - (mouseX - panX) * zoomFactor;
    panY = mouseY - (mouseY - panY) * zoomFactor;

    cellSize = (zoomLevel / 100) * bufferedGridData.grid_size;
    renderGrid(bufferedGridData.grids[currentFloor]);
    updateZoomLevel();
}

function handleGridHover(e) {
    const { row, col } = getCellCoordinates(e);
    const space = spacesData.find(s => s.floor === currentFloor && isPointInPolygon(row, col, s.polygon));
    if (space && foundEscapeRoutes) {
        const route = foundEscapeRoutes.find(r => r.id === space.id);
        if (route) {
            highlightPath(route.optimal_path);
        }
    }
}

function handleGridMouseOut() {
    renderGrid(bufferedGridData.grids[currentFloor]);
}

function getCellCoordinates(e) {
    const rect = gridContainer.getBoundingClientRect();
    const scaleX = gridContainer.querySelector('canvas').width / rect.width;
    const scaleY = gridContainer.querySelector('canvas').height / rect.height;

    const x = (e.clientX - rect.left - panX) * scaleX / (zoomLevel / 10000);
    const y = (e.clientY - rect.top - panY) * scaleY / (zoomLevel / 10000);

    const col = Math.floor(x / cellSize);
    const row = Math.floor(y / cellSize);

    return { row, col };
}

function isPointInPolygon(x, y, polygon) {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = (polygon[i][0] - bufferedGridData.bbox.min_x) / bufferedGridData.grid_size;
        const yi = (polygon[i][1] - bufferedGridData.bbox.min_y) / bufferedGridData.grid_size;
        const xj = (polygon[j][0] - bufferedGridData.bbox.min_x) / bufferedGridData.grid_size;
        const yj = (polygon[j][1] - bufferedGridData.bbox.min_y) / bufferedGridData.grid_size;

        const intersect = ((yi > y) !== (yj > y))
            && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
        if (intersect) inside = !inside;
    }
    return inside;
}

function highlightPath(path) {
    const canvas = gridContainer.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    
    // Redraw the grid
    renderGrid(bufferedGridData.grids[currentFloor]);
    
    // Highlight the path
    ctx.strokeStyle = 'rgba(255, 255, 0, 0.8)';
    ctx.lineWidth = 4;
    ctx.beginPath();
    path.forEach((point, index) => {
        if (point[2] === currentFloor) {
            const x = (point[1] + 0.5) * cellSize;
            const y = (point[0] + 0.5) * cellSize;
            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }
    });
    ctx.stroke();
}

function startPainting(row, col) {
    isPainting = true;
    isMouseDown = true;
    lastPaintedCell = { row, col };
    clearPreview();
    paint(row, col);
}

function stopPainting() {
    isPainting = false;
    isMouseDown = false;
    lastPreviewCell = lastPaintedCell;
    lastPaintedCell = null;
    if (paintedCells.size > 0) {
        const updates = Array.from(paintedCells).map(coord => {
            const [row, col] = coord.split(',').map(Number);
            return { floor: currentFloor, row, col, type: originalGridData.grids[currentFloor][row][col] };
        });
        batchUpdateCells(updates).then(() => {
            paintedCells.clear();
            renderGrid(bufferedGridData.grids[currentFloor]);
        });
    }
}

function paint(row, col) {
    clearPreview();

    if (currentType === 'start') {
        start = { floor: currentFloor, row, col };
    } else if (currentType === 'goal') {
        goals.push({ floor: currentFloor, row, col });
    } else if (currentTool === 'fill') {
        floodFill(currentFloor, row, col, originalGridData.grids[currentFloor][row][col]);
    } else {
        paintWithBrush(row, col);
        if (lastPaintedCell) {
            interpolatePaint(lastPaintedCell.row, lastPaintedCell.col, row, col);
        }
    }

    lastPaintedCell = { row, col };
    renderGrid(bufferedGridData.grids[currentFloor]);
    showPreview(row, col);
}

function paintWithBrush(centerRow, centerCol) {
    const updates = [];
    const halfSize = Math.floor(brushSize / 2);
    for (let i = 0; i < brushSize; i++) {
        for (let j = 0; j < brushSize; j++) {
            const row = centerRow - halfSize + i;
            const col = centerCol - halfSize + j;
            if (isValidCell(row, col)) {
                if (originalGridData.grids[currentFloor][row][col] != currentType){
                    originalGridData.grids[currentFloor][row][col] = currentType;
                    bufferedGridData.grids[currentFloor][row][col] = currentType;
                    updates.push({ floor: currentFloor, row, col, type: currentType });
                    paintedCells.add(`${row},${col}`);
                }
            }
        }
    }
    return updates;
}

function drawLine(startRow, startCol, endRow, endCol) {
    const updates = interpolatePaint(startRow, startCol, endRow, endCol);
    batchUpdateCells(updates).then(() => {
        renderGrid(bufferedGridData.grids[currentFloor]);
    });
}

function interpolatePaint(startRow, startCol, endRow, endCol) {
    const updates = [];
    const dx = Math.abs(endCol - startCol);
    const dy = Math.abs(endRow - startRow);
    const sx = startCol < endCol ? 1 : -1;
    const sy = startRow < endRow ? 1 : -1;
    let err = dx - dy;

    let currentRow = startRow;
    let currentCol = startCol;

    while (true) {
        updates.push(...paintWithBrush(currentRow, currentCol));

        if (currentRow === endRow && currentCol === endCol) break;
        const e2 = 2 * err;
        if (e2 > -dy) {
            err -= dy;
            currentCol += sx;
        }
        if (e2 < dx) {
            err += dx;
            currentRow += sy;
        }
    }
    return updates;
}
function floodFill(floor, row, col, targetElement) {
    const updates = [];
    const stack = [[row, col]];
    const seen = new Set();

    while (stack.length > 0) {
        const [r, c] = stack.pop();
        const key = `${r},${c}`;
        if (seen.has(key)) continue;
        seen.add(key);

        if (!isValidCell(r, c) || originalGridData.grids[floor][r][c] !== targetElement || targetElement === currentType) {
            continue;
        }

        originalGridData.grids[floor][r][c] = currentType;
        bufferedGridData.grids[floor][r][c] = currentType;
        updates.push({ floor, row: r, col: c, type: currentType });

        stack.push([r+1, c], [r-1, c], [r, c+1], [r, c-1]);
    }

    return updates;
}

function showPreview(row, col) {
    if (currentTool !== 'paint' || currentType === 'start' || currentType === 'goal') return;

    clearPreview();
    previewBrush(row, col);

    if (brushSize === 1 && lastPreviewCell) {
        previewInterpolation(lastPreviewCell.row, lastPreviewCell.col, row, col);
    }
    lastPreviewCell = { row, col };
}

function previewLine(startRow, startCol, endRow, endCol) {
    previewInterpolation(startRow, startCol, endRow, endCol);
}

function previewBrush(centerRow, centerCol) {
    const halfSize = Math.floor(brushSize / 2);
    for (let i = 0; i < brushSize; i++) {
        for (let j = 0; j < brushSize; j++) {
            const previewRow = centerRow - halfSize + i;
            const previewCol = centerCol - halfSize + j;
            previewCell(previewRow, previewCol);
        }
    }
}

function previewInterpolation(startRow, startCol, endRow, endCol) {
    const dx = Math.abs(endCol - startCol);
    const dy = Math.abs(endRow - startRow);
    const sx = startCol < endCol ? 1 : -1;
    const sy = startRow < endRow ? 1 : -1;
    let err = dx - dy;
    let currentRow = startRow;
    let currentCol = startCol;

    while (true) {
        previewBrush(currentRow, currentCol);

        if (currentRow === endRow && currentCol === endCol) break;
        const e2 = 2 * err;
        if (e2 > -dy) {
            err -= dy;
            currentCol += sx;
        }
        if (e2 < dx) {
            err += dx;
            currentRow += sy;
        }
    }
}

function previewCell(row, col) {
    if (!isValidCell(row, col)) return;
    const canvas = gridContainer.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = getCellColor(currentType);
    ctx.globalAlpha = 0.5;
    ctx.fillRect(col * cellSize, row * cellSize, cellSize, cellSize);
    ctx.globalAlpha = 1.0;
}

function clearPreview() {
    renderGrid(bufferedGridData.grids[currentFloor]);
}

function updateTransform() {
    const canvas = gridContainer.querySelector('canvas');
    if (canvas) {
        canvas.style.transform = transform.toString();
        inverseTransform = transform.inverse();
    }
}

function getCellCoordinates(e) {
    const canvas = gridContainer.querySelector('canvas');
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;

    // Get the mouse position relative to the canvas
    const mouseX = (e.clientX - rect.left) * scaleX;
    const mouseY = (e.clientY - rect.top) * scaleY;

    // Apply the inverse transform to get the world coordinates
    const point = inverseTransform.transformPoint(new DOMPoint(mouseX, mouseY));

    const col = Math.floor(point.x / cellSize);
    const row = Math.floor(point.y / cellSize);

    return { row, col };
}

function isValidCell(row, col) {
    return row >= 0 && row < bufferedGridData.grids[currentFloor].length &&
           col >= 0 && col < bufferedGridData.grids[currentFloor][0].length;
}

function setCurrentType(type, tool) {
    currentType = type;
    currentTool = tool;
}

function setCurrentTool(tool) {
    currentTool = tool;
}

function navigateToPreviousFloor() {
    if (currentFloor > 0) {
        currentFloor--;
        renderGrid(bufferedGridData.grids[currentFloor]);
        updateFloorDisplay();
    }
}

function navigateToNextFloor() {
    if (currentFloor < bufferedGridData.grids.length - 1) {
        currentFloor++;
        renderGrid(bufferedGridData.grids[currentFloor]);
        updateFloorDisplay();
    }
}

async function clearCurrentFloor() {
    const updates = [];
    for (let row = 0; row < originalGridData.grids[currentFloor].length; row++) {
        for (let col = 0; col < originalGridData.grids[currentFloor][row].length; col++) {
            originalGridData.grids[currentFloor][row][col] = 'empty';
            updates.push({ floor: currentFloor, row, col, type: 'empty' });
        }
    }
    await batchUpdateCells(updates);
    renderGrid(bufferedGridData.grids[currentFloor]);
}

async function addNewFloor() {
    const newFloor = originalGridData.grids[currentFloor].map(row => row.map(() => 'empty'));
    originalGridData.grids.push(newFloor);
    originalGridData.floors.push({
        elevation: originalGridData.floors[originalGridData.floors.length - 1].elevation + originalGridData.floors[originalGridData.floors.length - 1].height,
        height: originalGridData.floors[originalGridData.floors.length - 1].height
    });
    await applyWallBuffer();
    currentFloor = bufferedGridData.grids.length - 1;
    renderGrid(bufferedGridData.grids[currentFloor]);
    updateFloorDisplay();
}

async function removeCurrentFloor() {
    if (bufferedGridData.grids.length > 1) {
        originalGridData.grids.splice(currentFloor, 1);
        originalGridData.floors.splice(currentFloor, 1);
        await applyWallBuffer();
        currentFloor = Math.min(currentFloor, bufferedGridData.grids.length - 1);
        renderGrid(bufferedGridData.grids[currentFloor]);
        updateFloorDisplay();
    } else {
        showError('Cannot remove the last floor.');
    }
}

async function findPath() {
    if (!start || goals.length === 0) {
        showError('Please set start and at least one goal.');
        return;
    }

    try {
        await createOrFetchGraph();
        await getStairConnections();
        const response = await fetch('/api/find-path', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                grids: bufferedGridData.grids,
                grid_size: bufferedGridData.grid_size,
                floors: bufferedGridData.floors,
                bbox: bufferedGridData.bbox,
                start: start,
                goals: goals,
                allow_diagonal: allowDiagonal,
                minimize_cost: minimizeCost
            })
        });
        const data = await response.json();
        if (response.ok) {
            pathData = data.path;
            renderGrid(bufferedGridData.grids[currentFloor]);
        } else {
            showError(`Pathfinding error: ${data.error}`);
        }
    } catch (error) {
        console.error('Error:', error);
        showError(`An error occurred while finding the path: ${error.message}`);
    }
}

function highlightPath(path) {
    renderGrid(bufferedGridData.grids[currentFloor]);
    const canvas = gridContainer.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(255, 255, 0, 0.5)';
    path.forEach(point => {
        if (point[2] === currentFloor) {
            ctx.fillRect(point[1] * cellSize, point[0] * cellSize, cellSize, cellSize);
        }
    });

    // Highlight start and goals
    ctx.fillStyle = 'green';
    if (start.floor === currentFloor) {
        ctx.beginPath();
        ctx.arc((start.col + 0.5) * cellSize, (start.row + 0.5) * cellSize, cellSize / 2, 0, 2 * Math.PI);
        ctx.fill();
    }

    ctx.fillStyle = 'red';
    goals.forEach(goal => {
        if (goal.floor === currentFloor) {
            ctx.beginPath();
            ctx.arc((goal.col + 0.5) * cellSize, (goal.row + 0.5) * cellSize, cellSize / 2, 0, 2 * Math.PI);
            ctx.fill();
        }
    });
}

async function createOrFetchGraph() {
    console.log("Creating or fetching graph...");
    console.log("Original grids:", originalGridData.grids);
    console.log("Buffered grids:", bufferedGridData.grids);

    const createGraphResponse = await fetch('/api/create-graph', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            original_grids: originalGridData.grids,
            buffered_grids: bufferedGridData.grids,
            grid_size: bufferedGridData.grid_size,
            floors: bufferedGridData.floors,
            bbox: bufferedGridData.bbox,
            allow_diagonal: allowDiagonal,
            minimize_cost: minimizeCost,
        })
    });

    if (!createGraphResponse.ok) {
        const errorData = await createGraphResponse.json();
        console.error("Error response:", errorData);
        throw new Error(`HTTP error! status: ${createGraphResponse.status}, message: ${errorData.error || 'Unknown error'}`);
    }
}

async function calculateEscapeRoutes() {
    if (!goals || goals.length === 0) {
        await detectExits();
    }
    await updateSpaces();

    foundEscapeRoutes = [];
    let spacesWithViolations = [];
    let totalLength = 0;
    let stairwayDistance = -1;
    let spacesOverMaxDistance = [];
    let spacesWithoutExits = [];

    showProgress('Calculating graph...');

    // First, create the graph on the server
    try {
        await createOrFetchGraph();
        await getStairConnections();

        for (let i = 0; i < spacesData.length; i++) {
            const space = spacesData[i];
            updateProgress((i / spacesData.length) * 100, `Calculating route for space ${i + 1} of ${spacesData.length}`);

            try {
                const response = await fetch('/api/calculate-escape-route', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        space: space,
                        exits: goals.map(goal => [goal.row, goal.col, goal.floor]),
                        spaces: spacesData
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(`HTTP error! status: ${response.status}, message: ${errorData.error || 'Unknown error'}`);
                }

                const data = await response.json();
                foundEscapeRoutes.push(data.escape_route);

                // Check rules
                const violations = data.escape_route.violations;
                if (violations['general'].length > 0 || violations['daytime'].length > 0 || violations['nighttime'].length > 0) {
                    spacesWithViolations.push({space: space.name, violations});
                }

                // Update statistics
                if (data.escape_route.distance) {
                    totalLength = Math.max(totalLength, data.escape_route.distance);
                    stairwayDistance = Math.max(stairwayDistance, data.escape_route.distance_to_stair);
                    if (data.escape_route.distance_to_stair > maxStairDistance || data.escape_route.distance > maxStairDistance) {
                        spacesOverMaxDistance.push(data.escape_route.space_name);
                    }
                } else {
                    spacesWithoutExits.push(data.escape_route.space_name);
                }

                // Render the current progress
                displayViolations(spacesWithViolations);
                renderGrid(bufferedGridData.grids[currentFloor]);

            } catch (error) {
                console.error('Error calculating escape route for space:', space.name, error);
            }
        }

    } catch (error) {
        console.error('Error creating graph:', error);
        showError(`An error occurred while creating the graph: ${error.message}`);
    }

    document.getElementById('update-ifc-button').style.display = 'block';
    document.getElementById('export-pdf-button').style.display = 'block';
    hideProgress();

    // Display final results
    const pathLengthsElement = document.getElementById('path-lengths');
    pathLengthsElement.innerHTML = `
        <h3>Escape Route Lengths:</h3>
        <p>Longest escape route: ${totalLength.toFixed(2)} meters</p>
        <p>Longest distance to stairway: ${stairwayDistance.toFixed(2)} meters</p>
        <p>Spaces over max stair distance: ${spacesOverMaxDistance.join(', ') || 'None'}</p>
        <p>Spaces with NO escape route: ${spacesWithoutExits.join(', ') || 'None'}</p>
    `;

    renderGrid(bufferedGridData.grids[currentFloor]);
    //await updateIfcWithRoutes();
}
async function updateIfcWithRoutes() {
    if (!foundEscapeRoutes) {
        showError(`Please calculate the routes first using the calculate all button`);
        return;
    }

    let ifcFile;
    if (isIFC) {
        // If the original upload was an IFC file
        ifcFile = file;
//    } else if (originalGridData.original_ifc_filename) {
        // If a JSON was uploaded with a linked IFC file
//        ifcFile = await fetchLinkedIFCFile(originalGridData.original_ifc_filename);
    } else {
        // If no IFC file is linked, use the uploaded one
        const fileInput = document.getElementById('ifc-file-input');
        if (fileInput.files.length === 0) {
            showError('Please attach a .ifc file');
            return;
        }
        ifcFile = fileInput.files[0];
    }

    const formData = new FormData();
    formData.append('file', ifcFile);
    formData.append('routes', JSON.stringify(foundEscapeRoutes));
    formData.append('grid_size', bufferedGridData.grid_size);
    formData.append('bbox', JSON.stringify(bufferedGridData.bbox));
    formData.append('floors', JSON.stringify(bufferedGridData.floors));

    try {
        const response = await fetch('/api/update-ifc-with-routes', {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = ifcFile.name.replace('.ifc', '_with_routes.ifc');
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
        } else {
            const errorData = await response.json();
            showError(`Error updating IFC: ${errorData.error}`);
        }
    } catch (error) {
        console.error('Error:', error);
        showError(`An error occurred while updating the IFC file: ${error.message}`);
    }
}

async function exportPdfReport() {
    if (!foundEscapeRoutes) {
        showError('Please calculate escape routes first.');
        return;
    }

    try {
        const response = await fetch('/api/generate-pdf-report', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                escape_routes: foundEscapeRoutes,
                grid_size: bufferedGridData.grid_size,
                floors: bufferedGridData.floors,
                'filename': file.name
            })
        });

        if (!response.ok) {
            throw new Error('Network response was not ok');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = file.name.split(".")[0] + '_escape_routes_report.pdf';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Error:', error);
        showError(`An error occurred while generating the PDF report: ${error.message}`);
    }
}

// Helper function to fetch the linked IFC file
async function fetchLinkedIFCFile(filename) {
    const response = await fetch(`/api/get-linked-ifc-file/${filename}`);
    if (!response.ok) {
        throw new Error('Failed to fetch linked IFC file');
    }
    return response.blob();
}

async function handleIfcFileSelection(event) {
    const selectedFile = event.target.files[0];
    if (selectedFile) {
        const formData = new FormData();
        formData.append('file', selectedFile);

        try {
            const response = await fetch('/api/process-file', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

            const result = await response.json();
            // Merge the IFC data with the existing JSON data
            mergeIfcDataWithJson(result);
        } catch (error) {
            console.error('Error processing IFC file:', error);
            showError('An error occurred while processing the IFC file.');
        }
    }
}

function displayViolations(spacesWithViolations) {
    const violationsElement = document.getElementById('violations');
    if (spacesWithViolations.length === 0) {
        violationsElement.innerHTML = '<p>No rule violations found.</p>';
        return;
    }

    let violationsHTML = '<h3 class="text-lg font-semibold mb-2">Rule Violations:</h3>';
    spacesWithViolations.forEach(({space, violations}) => {
        violationsHTML += `<h4 class="text-md font-semibold mt-2">${space}:</h4>`;
        for (const [timeOfDay, violationList] of Object.entries(violations)) {
            if (violationList.length > 0) {
                violationsHTML += `<h5 class="text-sm font-semibold mt-1">${timeOfDay}:</h5><ul class="list-disc pl-5">`;
                violationList.forEach(violation => {
                    violationsHTML += `<li class="text-sm">${violation}</li>`;
                });
                violationsHTML += '</ul>';
            }
        }
    });

    violationsElement.innerHTML = violationsHTML;
}

function handleMaxStairDistanceChange(e) {
    maxStairDistance = parseInt(e.target.value);
    maxStairDistanceDisplay.textContent = `${maxStairDistance} m`;
    if (foundEscapeRoutes) {
        renderGrid(bufferedGridData.grids[currentFloor]);
    }
}

function generateRandomColor() {
    const hue = Math.floor(Math.random() * 360);
    return `hsla(${hue}, 70%, 70%, 50%)`;
}

function updateBufferForPaintedCells() {
    // This function should now use applyWallBuffer
    applyWallBuffer();
}

async function applyWallBuffer() {
    if (!Array.isArray(originalGridData.grids) || !originalGridData.grids.every(Array.isArray)) {
        console.error('Invalid grid data structure', originalGridData.grids);
        throw new Error('Invalid grid data structure. Please refresh the page and try again.');
    }

    try {
        const response = await fetch('/api/apply-wall-buffer', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                grids: originalGridData.grids,
                wall_buffer: wallBuffer,
                grid_size: originalGridData.grid_size,
                floors: originalGridData.floors,
                bbox: originalGridData.bbox
            })
        });
        const data = await response.json();
        if (response.ok) {
            if (Array.isArray(data.buffered_grids) && data.buffered_grids.every(Array.isArray)) {
                bufferedGridData = {...originalGridData, grids: data.buffered_grids};
                renderGrid(bufferedGridData.grids[currentFloor]);
            } else {
                throw new Error('Received invalid grid data from server');
            }
        } else {
            throw new Error(data.error || 'An error occurred while applying the wall buffer.');
        }
    } catch (error) {
        console.error('Error:', error);
        throw error;
    }
}

async function updateCell(floor, row, col, cellType) {
    try {
        const response = await fetch('/api/update-cell', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                grids: originalGridData.grids,
                floor: floor,
                row: row,
                col: col,
                cell_type: cellType,
                wall_buffer: wallBuffer,
                grid_size: originalGridData.grid_size,
                floors: originalGridData.floors,
                bbox: originalGridData.bbox
            })
        });
        const data = await response.json();
        if (response.ok) {
            originalGridData.grids = data.original_grids;
            bufferedGridData = {...originalGridData, grids: data.buffered_grids};
        } else {
            throw new Error(data.error || 'An error occurred while updating the cell.');
        }
    } catch (error) {
        console.error('Error:', error);
        showError('An error occurred while updating the cell.');
    }
}

async function batchUpdateCells(updates) {
    try {
        const response = await fetch('/api/batch-update-cells', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                grids: originalGridData.grids,
                updates: updates,
                wall_buffer: wallBuffer,
                grid_size: originalGridData.grid_size,
                floors: originalGridData.floors,
                bbox: originalGridData.bbox
            })
        });
        const data = await response.json();
        if (response.ok) {
            originalGridData.grids = data.original_grids;
            bufferedGridData = {...originalGridData, grids: data.buffered_grids};
        } else {
            throw new Error(data.error || 'An error occurred while updating cells.');
        }
    } catch (error) {
        console.error('Error:', error);
        showError('An error occurred while updating cells.');
    }
}

async function detectExits() {
    try {
        const response = await fetch('/api/detect-exits', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                grids: bufferedGridData.grids,
                grid_size: bufferedGridData.grid_size,
                floors: bufferedGridData.floors,
                bbox: bufferedGridData.bbox
            })
        });
        const data = await response.json();
        if (response.ok) {
            goals = data.exits.map(exit => ({ row: exit[0], col: exit[1], floor: exit[2] }));
            renderGrid(bufferedGridData.grids[currentFloor]);
            //showMessage('Exits detected and added as goals.');
        } else {
            showError(`Exit detection error: ${data.error}`);
        }
    } catch (error) {
        console.error('Error:', error);
        showError(`An error occurred while detecting exits: ${error.message}`);
    }
}

function handleZoomChange(e) {
    const oldZoom = zoomLevel;
    zoomLevel = parseInt(e.target.value);
    const zoomFactor = zoomLevel / oldZoom;

    const rect = gridContainer.getBoundingClientRect();
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    // Calculate the center of the grid in world space
    const center = inverseTransform.transformPoint(new DOMPoint(centerX, centerY));

    // Update the transform
    transform = transform.translate(center.x, center.y)
                         .scale(zoomFactor)
                         .translate(-center.x, -center.y);

    cellSize = (zoomLevel / cellBufferScale) * bufferedGridData.grid_size;
    renderGrid(bufferedGridData.grids[currentFloor]);
    updateZoomLevel();
}

function updateZoomLevel() {
    document.getElementById('zoom-level').textContent = `${(zoomLevel / 100).toFixed(2)}%`;
    zoomSlider.value = zoomLevel;
}

function handleBrushSizeChange(e) {
    brushSize = parseInt(e.target.value);
    document.getElementById('brush-size-display').textContent = brushSize;
}

function handleWallBufferChange(e) {
    wallBuffer = parseInt(e.target.value);
    const actualBufferSize = wallBuffer * bufferedGridData.grid_size;
    document.getElementById('wall-buffer-display').textContent = actualBufferSize.toFixed(2);
    applyWallBuffer();
}

function updateFloorDisplay() {
    let currentElev = (Math.round(bufferedGridData.floors[currentFloor]['elevation'] * 100) / 100).toFixed(2);
    let currentHeight = (Math.round((bufferedGridData.floors[currentFloor]['elevation'] + bufferedGridData.floors[currentFloor]['height']) * 100) / 100).toFixed(2);
    document.getElementById('current-floor').textContent = `Floor ${bufferedGridData.floors[currentFloor]['name']}: ${currentFloor + 1} / ${bufferedGridData.grids.length}`;
    document.getElementById('current-floor-info').textContent = `Elevation: ${currentElev} m to ${currentHeight} m`;
}

function showGridEditor() {
    document.getElementById('grid-editor').classList.remove('hidden');
    document.getElementById('pathfinder').classList.remove('hidden');
}

function showProgress(message) {
    progressContainer.classList.remove('hidden');
    progressBar.style.width = '0%';
    progressText.textContent = message;
}

function updateProgress(percentage, message) {
    progressBar.style.width = `${percentage}%`;
    progressText.textContent = `${percentage.toFixed(1)}%: ${message}`;
}

function hideProgress() {
    progressContainer.classList.add('hidden');
}

function showError(message) {
    console.error(message);
    alert(message);  // You can replace this with a more sophisticated error display method
}

function showMessage(message) {
    console.log(message);
    alert(message);  // You can replace this with a more sophisticated message display method
}

// Initialize the application
function init() {
    // Set initial values for sliders
    zoomSlider.min = 100;  // 10% minimum zoom
    zoomSlider.max = 25000; // 2000% maximum zoom
    zoomSlider.value = zoomLevel;
    brushSizeSlider.value = brushSize;
    wallBufferSlider.value = wallBuffer;

    // Update displays
    updateTransform();
    document.getElementById('brush-size-display').textContent = brushSize;
    const initialBufferSize = wallBuffer * bufferedGridData.grid_size;
    document.getElementById('wall-buffer-display').textContent = initialBufferSize.toFixed(2);
}

// Call the init function when the DOM is fully loaded
//document.addEventListener('DOMContentLoaded', init);
document.addEventListener('DOMContentLoaded', () => {
    init();
    const observer = new MutationObserver((mutations) => {
        if (gridContainer.querySelector('canvas')) {
            //initializeDragFunctionality();
            observer.disconnect();
            //console.log("Dragging initiated");
        }
    });
});