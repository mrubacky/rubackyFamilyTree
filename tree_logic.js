document.addEventListener('DOMContentLoaded', () => {
    const svgId = '#familyTreeSvg';
    // Details panel elements
    const detailNameEl = document.getElementById('detailName');
    const detailOriginEl = document.getElementById('detailOrigin');
    const detailYearInfoEl = document.getElementById('detailYearInfo');
    const detailRawTextEl = document.getElementById('detailRawText');

    const svgContainer = document.querySelector('.tree-visualization-container');
    // Use clientWidth for initial, but ensure it's not too small
    const calculatedInitialWidth = svgContainer.clientWidth > 800 ? svgContainer.clientWidth : 800;
    const initialHeight = 700;

    const margin = { top: 50, right: 150, bottom: 50, left: 200 }; // Increased top/bottom margin a bit
    // width and height are for the drawing area *inside* the margins. They are not fixed.
    // The SVG element total size will be dynamic.

    // This is the main <g> element where the tree is drawn.
    // Its initial transform sets up the margins. This transform will be updated.
    const g = d3.select(svgId)
        .attr("width", calculatedInitialWidth) // Set initial SVG size
        .attr("height", initialHeight)
      .append("g")
        .attr("transform", `translate(${margin.left},${margin.top})`);

    let nodeIndex = 0;
    const duration = 500;
    let rootNodeD3;

    const treeLayout = d3.tree().nodeSize([40, 260]); // nodeSize([verticalNodeSep, horizontalNodeSep])

    d3.json("family_tree.json").then(familyData => {
        if (!familyData || (!familyData.name && !familyData.id)) {
            console.error("Family data is empty or not in the expected format:", familyData);
            displayError("Failed to load family tree data. Ensure 'family_tree.json' is valid.");
            return;
        }

        rootNodeD3 = d3.hierarchy(familyData, d => d.children);
        // Initial position for the root node (relative to the <g> element's origin)
        rootNodeD3.x0 = initialHeight / 2 - margin.top; // Attempt to center vertically initially
        rootNodeD3.y0 = 0;      // Start at the left

        if (rootNodeD3.children) {
            rootNodeD3.children.forEach(parentOfMe => {
                if (parentOfMe.children) {
                    parentOfMe.children.forEach(collapseRecursively);
                }
            });
        }
        updateTree(rootNodeD3);

    }).catch(error => {
        console.error("Error loading or parsing family_tree.json:", error);
        displayError(`Error loading data: ${error.message}.`);
    });

    function displayError(message) {
        const treeContainer = document.querySelector('.tree-visualization-container');
        if (treeContainer) {
            treeContainer.innerHTML = `<p style="color: red; text-align: center; padding: 20px;">${message}</p>`;
        }
    }

    function collapseRecursively(d) {
        if (d.children) {
            d._children = d.children;
            d._children.forEach(collapseRecursively);
            d.children = null;
        } else if (d._children) { // If already collapsed but we need to ensure deep collapse
            d._children.forEach(collapseRecursively);
        }
    }

    function updateTree(source) {
        // Ensure source node has x0, y0 (previous positions) defined for transitions.
        if (source.x0 === undefined) {
            // If source.x is also undefined (e.g. root first time), use a sensible default.
            source.x0 = source.x !== undefined ? source.x : (initialHeight / 2 - margin.top);
        }
        if (source.y0 === undefined) {
            source.y0 = source.y !== undefined ? source.y : 0;
        }

        const treeDataLayout = treeLayout(rootNodeD3);
        let nodes = treeDataLayout.descendants();
        let links = treeDataLayout.links();

        // Calculate the extent of the nodes in their own coordinate system (relative to <g>'s origin)
        let minX_node = Infinity, maxX_node = -Infinity; // Vertical node extent
        let minY_node = Infinity, maxY_node = -Infinity; // Horizontal node extent

        nodes.forEach(d => {
            if (d.x < minX_node) minX_node = d.x;
            if (d.x > maxX_node) maxX_node = d.x;
            if (d.y < minY_node) minY_node = d.y; // minY_node will often be 0 for root
            if (d.y > maxY_node) maxY_node = d.y;
        });
        
        // If there are no nodes, min/max will be Infinity; handle this.
        if (nodes.length === 0) {
            minX_node = 0; maxX_node = 0; minY_node = 0; maxY_node = 0;
        }


        // Calculate the actual width and height needed for the tree content itself
        const contentWidth = maxY_node - minY_node;
        const contentHeight = maxX_node - minX_node;

        // Calculate the required SVG dimensions including margins and buffer
        const requiredSvgWidth = contentWidth + margin.left + margin.right + 250; // Buffer for text
        const requiredSvgHeight = contentHeight + margin.top + margin.bottom + 60; // Buffer

        // Update overall SVG dimensions (the <svg> element itself)
        d3.select(svgId)
            .attr("width", Math.max(calculatedInitialWidth, requiredSvgWidth))
            .attr("height", Math.max(initialHeight, requiredSvgHeight));

        // Dynamically adjust the translation of the main <g> element.
        // This ensures that the top-leftmost part of the tree content
        // is positioned correctly after considering the margins.
        // We want the point (minY_node, minX_node) in the tree's coordinate system
        // to appear at (margin.left, margin.top) in the SVG's coordinate system.
        g.attr("transform", `translate(${margin.left - minY_node}, ${margin.top - minX_node})`);

        // --- Node rendering ---
        const node = g.selectAll('g.node') // Select all nodes within the main <g>
            .data(nodes, d => d.id || (d.id = d.data.id || `node-${++nodeIndex}`));

        const nodeEnter = node.enter().append('g')
            .attr('class', d => `node country-${sanitizeForCss(d.data.countryOfOrigin || 'unknown')}`)
            // New nodes start at source's *previous* position (relative to <g>)
            .attr('transform', `translate(${source.y0},${source.x0})`)
            .on('click', (event, d) => {
                toggleChildren(d);
                updateTree(d);
                displayDetails(d.data);
            });

        nodeEnter.append('circle')
            .attr('r', 1e-6); // Start small

        nodeEnter.append('text')
            .attr('dy', '.35em')
            .attr('x', d => d.children || d._children ? -13 : 13)
            .attr('text-anchor', d => d.children || d._children ? 'end' : 'start')
            .text(d => d.data.name || "N/A");

        const nodeUpdate = nodeEnter.merge(node);

        nodeUpdate.transition()
            .duration(duration)
            // Nodes transition to their new x, y positions (relative to <g>)
            .attr('transform', d => `translate(${d.y},${d.x})`);

        nodeUpdate.select('circle')
            .attr('r', 7)
            .style('fill', d => d._children ? 'lightsteelblue' : (d.children ? '#fff' : '#aaa')); // Grey if leaf

        nodeUpdate.select('text').style('fill-opacity', 1);

        const nodeExit = node.exit().transition()
            .duration(duration)
            // Exiting nodes go to source's *new* position (relative to <g>)
            .attr('transform', `translate(${source.y},${source.x})`)
            .remove();

        nodeExit.select('circle').attr('r', 1e-6);
        nodeExit.select('text').style('fill-opacity', 1e-6);

        // --- Link rendering ---
        const link = g.selectAll('path.link') // Select links within the main <g>
            .data(links, d => d.target.id);

        const linkEnter = link.enter().insert('path', 'g')
            .attr('class', 'link')
            .attr('d', d_link => {
                // New links start from source's *previous* position
                const o = { x: source.x0, y: source.y0 };
                return diagonal(o, o);
            });

        linkEnter.merge(link).transition()
            .duration(duration)
            // Links transition to use new source and target positions (relative to <g>)
            .attr('d', d_link => diagonal(d_link.source, d_link.target));

        link.exit().transition()
            .duration(duration)
            // Exiting links go to source's *new* position
            .attr('d', d_link => {
                const o = { x: source.x, y: source.y };
                return diagonal(o, o);
            })
            .remove();

        // Stash the new positions for all nodes for next transition.
        nodes.forEach(d_node => {
            d_node.x0 = d_node.x;
            d_node.y0 = d_node.y;
        });
    }

    function toggleChildren(d) {
        if (d.children) {
            d._children = d.children;
            d.children = null;
        } else {
            d.children = d._children;
            d._children = null;
        }
    }

    function diagonal(s_node, t_node) { // s_node and t_node are D3 nodes with x,y properties
        const sy = s_node.y !== undefined ? s_node.y : 0; // Horizontal position of source
        const sx = s_node.x !== undefined ? s_node.x : 0; // Vertical position of source
        const ty = t_node.y !== undefined ? t_node.y : 0; // Horizontal position of target
        const tx = t_node.x !== undefined ? t_node.x : 0; // Vertical position of target

        if (s_node.y === undefined || s_node.x === undefined || t_node.y === undefined || t_node.x === undefined) {
            console.warn("Diagonal function received node with undefined coordinates:", "s_node:", s_node, "t_node:", t_node);
        }
        // Path for a horizontal tree: M <start-y> <start-x> C <c1-y> <c1-x>, <c2-y> <c2-x>, <end-y> <end-x>
        return `M ${sy} ${sx}
                C ${(sy + ty) / 2} ${sx},
                  ${(sy + ty) / 2} ${tx},
                  ${ty} ${tx}`;
    }

    function displayDetails(data) {
        detailNameEl.textContent = data.name || 'N/A';
        const originText = data.details?.origin || 'N/A';
        const yearInfoText = data.details?.year_info || 'N/A';
        const rawText = data.details?.raw || data.name;

        detailOriginEl.textContent = originText;
        detailYearInfoEl.textContent = yearInfoText;
        detailRawTextEl.textContent = rawText;
        
        detailOriginEl.className = '';
        if (data.countryOfOrigin) {
            detailOriginEl.classList.add(`country-text-${sanitizeForCss(data.countryOfOrigin)}`);
        }
    }

    function sanitizeForCss(className) {
        if (!className || typeof className !== 'string') return 'unknown';
        return className.replace(/[^a-zA-Z0-9-_]/g, '_').toLowerCase();
    }

    // Resize handler (optional, can be basic or removed if scrolling is sufficient)
    // window.addEventListener('resize', () => { /* Basic resize logic if needed */ });
});