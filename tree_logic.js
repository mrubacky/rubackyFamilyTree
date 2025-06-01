document.addEventListener('DOMContentLoaded', () => {
    const svgId = '#familyTreeSvg';
    const detailNameEl = document.getElementById('detailName');
    const detailOriginEl = document.getElementById('detailOrigin');
    const detailYearInfoEl = document.getElementById('detailYearInfo');
    const detailRawTextEl = document.getElementById('detailRawText');

    const svgContainer = document.querySelector('.tree-visualization-container');
    let calculatedInitialWidth = svgContainer.clientWidth > 600 ? svgContainer.clientWidth : 600; // Ensure a min drawing width
    const initialHeight = 600; // Base height, will grow

    const margin = { top: 40, right: 120, bottom: 40, left: 180 }; // Adjusted margins slightly

    // The main SVG element
    const svgElement = d3.select(svgId)
        .attr("width", calculatedInitialWidth)
        .attr("height", initialHeight);

    // The <g> element that will contain all tree elements and be transformed by zoom/pan
    // This 'g' will also handle the margin translations initially.
    const g = svgElement.append("g")
        .attr("transform", `translate(${margin.left},${margin.top})`);

    let nodeIndex = 0;
    const duration = 500;
    let rootNodeD3;

    // Define tree layout - nodeSize helps control spacing better
    const treeLayout = d3.tree().nodeSize([40, 250]); // [verticalNodeSeparation, horizontalNodeSeparation]

    // --- Zoom Functionality ---
    const zoomBehavior = d3.zoom()
        .scaleExtent([0.1, 3]) // Min/max zoom levels
        .on("zoom", (event) => {
            g.attr("transform", event.transform); // Apply D3's calculated zoom transform to the main <g>
        });

    svgElement.call(zoomBehavior); // Attach zoom behavior to the main SVG element

    // --- Load Data ---
    d3.json("family_tree.json").then(familyData => {
        if (!familyData || (!familyData.name && !familyData.id)) {
            console.error("Family data error:", familyData);
            displayError("Failed to load family tree data.");
            return;
        }

        rootNodeD3 = d3.hierarchy(familyData, d => d.children);
        // Set initial positions for the root node, relative to the <g> element's origin
        rootNodeD3.x0 = (initialHeight - margin.top - margin.bottom) / 2; // Initial vertical center within drawing area
        rootNodeD3.y0 = 0; // Start at the left of the drawing area

        // Initial collapse strategy
        if (rootNodeD3.children) {
            rootNodeD3.children.forEach(parentOfMe => {
                if (parentOfMe.children) {
                    parentOfMe.children.forEach(collapseRecursively);
                }
            });
        }
        updateTree(rootNodeD3);

        // Optional: Center the tree initially after first layout using zoom.transform
        // This needs tree bounds, so call it after first updateTree or with slight delay.
        // centerTree(rootNodeD3); // We'll define this later if needed. Basic zoom is first step.

    }).catch(error => {
        console.error("Error loading family_tree.json:", error);
        displayError(`Error loading data: ${error.message}.`);
    });

    function displayError(message) {
        svgContainer.innerHTML = `<p style="color: red; text-align: center; padding: 20px;">${message}</p>`;
    }

    function collapseRecursively(d) {
        if (d.children) {
            d._children = d.children;
            d._children.forEach(collapseRecursively);
            d.children = null;
        } else if (d._children) {
            d._children.forEach(collapseRecursively);
        }
    }

    function updateTree(source) {
        if (source.x0 === undefined) {
            source.x0 = (initialHeight - margin.top - margin.bottom) / 2;
        }
        if (source.y0 === undefined) {
            source.y0 = 0;
        }

        const treeDataLayout = treeLayout(rootNodeD3);
        let nodes = treeDataLayout.descendants();
        let links = treeDataLayout.links();

        let minX_node = Infinity, maxX_node = -Infinity;
        let minY_node = Infinity, maxY_node = -Infinity;
        nodes.forEach(d => {
            if (d.x < minX_node) minX_node = d.x;
            if (d.x > maxX_node) maxX_node = d.x;
            if (d.y < minY_node) minY_node = d.y;
            if (d.y > maxY_node) maxY_node = d.y;
        });
        
        if (nodes.length === 0) { minX_node = maxX_node = minY_node = maxY_node = 0; }

        // Calculate total width/height needed for the tree content itself (within the <g>)
        const contentWidth = maxY_node - minY_node;
        const contentHeight = maxX_node - minX_node;

        // The SVG element needs to be large enough for this content + margins
        // The origin of the <g> element is effectively (margin.left - minY_node, margin.top - minX_node)
        // relative to the SVG's (0,0) if we want the tree's bounding box to start at margins.
        // However, with zoom, we usually let the <g> be transformed by zoom,
        // and size the SVG to a reasonable initial viewport, and let it grow if necessary to show all content if NOT zoomed out.
        
        // The actual drawing area for nodes (d.x, d.y) is relative to the 'g' element.
        // The 'g' element itself has an initial transform for margins. Zoom then transforms 'g'.
        // We need to size the SVG so scrollbars appear correctly if the 'g' (with its content) is panned/zoomed
        // such that its effective bounding box exceeds SVG dimensions.

        // Dynamically size the SVG to encompass the laid-out tree plus margins
        // This ensures that when zoomed out, there's enough SVG space.
        // The minY_node and minX_node are relative to the 'g' element's origin.
        // So, the total extent is from (minY_node + g_translateX) to (maxY_node + g_translateX)
        // This is complex. For now, ensure SVG is large enough for the span.
        const currentTransform = d3.zoomTransform(svgElement.node()); // Get current zoom transform if needed

        // The required width/height for the *content within g*
        // minY_node, minX_node can be negative if tree grows left/up from initial root pos.
        const effectiveContentWidth = maxY_node - minY_node;
        const effectiveContentHeight = maxX_node - minX_node;

        // The SVG needs to be large enough to contain this, considering margins.
        // The content's top-left will be at (minY_node, minX_node) within the <g>
        // The <g> is initially translated by (margin.left, margin.top)
        // When zoomed/panned, event.transform gives the new state for <g>
        
        // Resize SVG based on current tree extent. This is important for scrollbars.
        // The minX_node, minY_node are coordinates *within* the main `g` element.
        // The `g` element itself has the zoom transform applied + initial margin transform.
        // For SVG sizing, consider the span of nodes and add margins.
        const svgWidthRequired = (maxY_node - minY_node) + margin.left + margin.right + 200; // Buffer
        const svgHeightRequired = (maxX_node - minX_node) + margin.top + margin.bottom + 100; // Buffer
        
        svgElement
            .attr("width", Math.max(calculatedInitialWidth, svgWidthRequired))
            .attr("height", Math.max(initialHeight, svgHeightRequired));


        // --- Node rendering (within the 'g' element) ---
        const node = g.selectAll('g.node')
            .data(nodes, d => d.id || (d.id = d.data.id || `node-${++nodeIndex}`));

        const nodeEnter = node.enter().append('g')
            .attr('class', d => {
                const dominant = getDominantOrigin(d.data.origin_mix, d.data.countryOfOrigin);
                return `node country-${sanitizeForCss(dominant)}`;
            })
            .attr('transform', `translate(${source.y0},${source.x0})`)
            .on('click', (event, d) => {
                // Prevent click from propagating to zoom/pan behavior if it's a node click
                event.stopPropagation(); 
                toggleChildren(d);
                updateTree(d);
                displayDetails(d.data);
            });

        nodeEnter.append('circle').attr('r', 1e-6);
        nodeEnter.append('text')
            .attr('dy', '.35em')
            .attr('x', d => d.children || d._children ? -13 : 13)
            .attr('text-anchor', d => d.children || d._children ? 'end' : 'start')
            .text(d => d.data.name || "N/A");

        const nodeUpdate = nodeEnter.merge(node);
        nodeUpdate.transition().duration(duration)
            .attr('transform', d => `translate(${d.y},${d.x})`);
        nodeUpdate.select('circle').attr('r', 7)
            .style('fill', d => d._children ? 'lightsteelblue' : (d.children ? '#fff' : '#aaa'));
        nodeUpdate.select('text').style('fill-opacity', 1);

        const nodeExit = node.exit().transition().duration(duration)
            .attr('transform', `translate(${source.y},${source.x})`).remove();
        nodeExit.select('circle').attr('r', 1e-6);
        nodeExit.select('text').style('fill-opacity', 1e-6);

        // --- Link rendering (within the 'g' element) ---
        const link = g.selectAll('path.link')
            .data(links, d => d.target.id);

        const linkEnter = link.enter().insert('path', 'g')
            .attr('class', 'link')
            .attr('d', d_link => { const o = { x: source.x0, y: source.y0 }; return diagonal(o, o); });

        linkEnter.merge(link).transition().duration(duration)
            .attr('d', d_link => diagonal(d_link.source, d_link.target));

        link.exit().transition().duration(duration)
            .attr('d', d_link => { const o = { x: source.x, y: source.y }; return diagonal(o, o); })
            .remove();

        nodes.forEach(d_node => { d_node.x0 = d_node.x; d_node.y0 = d_node.y; });
    }

    function toggleChildren(d) {
        if (d.children) {
            d._children = d.children; d.children = null;
        } else {
            d.children = d._children; d._children = null;
        }
    }

    function diagonal(s_node, t_node) {
        const sy = s_node.y !== undefined ? s_node.y : 0;
        const sx = s_node.x !== undefined ? s_node.x : 0;
        const ty = t_node.y !== undefined ? t_node.y : 0;
        const tx = t_node.x !== undefined ? t_node.x : 0;
        if (s_node.y === undefined || s_node.x === undefined || t_node.y === undefined || t_node.x === undefined) {
            console.warn("Diagonal received undefined coords:", "s:", s_node, "t:", t_node);
        }
        return `M ${sy} ${sx} C ${(sy + ty) / 2} ${sx}, ${(sy + ty) / 2} ${tx}, ${ty} ${tx}`;
    }

    function displayDetails(data) { /* ... your existing displayDetails ... */
        detailNameEl.textContent = data.name || 'N/A';
        const breakdown = data.details?.origin_breakdown;
        let breakdownHtml = "N/A";
        if (breakdown && typeof breakdown === 'object' && Object.keys(breakdown).length > 0) {
            breakdownHtml = "<ul>";
            const sortedBreakdown = Object.entries(breakdown).sort(([,a],[,b]) => b-a);
            for (const [country, percentage] of sortedBreakdown) {
                if (percentage > 0.001) {
                     breakdownHtml += `<li>${country}: ${(percentage * 100).toFixed(1)}%</li>`;
                }
            }
            breakdownHtml += "</ul>";
        }
        detailOriginEl.innerHTML = breakdownHtml;
        detailYearInfoEl.textContent = data.details?.year_info || 'N/A';
        detailRawTextEl.textContent = data.details?.raw || data.name;
    }

    function sanitizeForCss(className) { /* ... your existing sanitizeForCss ... */
        if (!className || typeof className !== 'string') return 'unknown';
        return className.replace(/[^a-zA-Z0-9-_]/g, '_').toLowerCase();
    }
    
    function getDominantOrigin(originMix, fallbackCountry) { /* ... your existing getDominantOrigin ... */
        if (originMix && typeof originMix === 'object' && Object.keys(originMix).length > 0) {
            let dominantCountry = 'unknown'; 
            let maxPercentage = 0;
            let hasKnownOrigin = false;
            for (const country in originMix) {
                const percentage = originMix[country];
                const countryLower = country.toLowerCase();
                if (countryLower !== 'unknown' && percentage > maxPercentage) {
                    maxPercentage = percentage;
                    dominantCountry = country;
                    hasKnownOrigin = true;
                } else if (countryLower !== 'unknown' && percentage === maxPercentage) {
                    if (country.localeCompare(dominantCountry) < 0) {
                         dominantCountry = country;
                    }
                     hasKnownOrigin = true;
                }
            }
            if (!hasKnownOrigin && originMix["Unknown"] >= 0.5) { 
                 return 'unknown';
            }
            if (dominantCountry === 'unknown' && fallbackCountry) {
                return fallbackCountry;
            }
            return dominantCountry; 
        }
        return fallbackCountry || 'unknown';
    }

    // Optional: Debounced resize handler can be basic or removed if zoom/pan is primary
    // window.addEventListener('resize', () => { /* ... */ });
});