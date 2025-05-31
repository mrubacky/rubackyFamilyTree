import csv
import re
import json

# Helper to parse individual cell data
def parse_person_cell(cell_text, cell_id):
    if not cell_text or cell_text.strip().lower() in ["mother?", "father?", "#error!"]:
        return None

    name = cell_text.strip()
    origin = None
    year_info = None
    details_text = "" # Full original string for bio

    # Regex to capture Name (Origin, Year Info) or Name (Origin Year Info)
    # Handles formats like:
    # "Mary Duggan (Ireland, 1881)"
    # "Stephen J Duggan, (Ireland)"
    # "Michael Burns (Ireland, 1841-1880)"
    # "Robert Pond (England, 1612-1627)"
    # "Gov. William Bradford (England 1620 *Mayflower)"
    # "John Schmidt (Germany, 1740-1767)"
    # "William Furbish (Scotland 1635- )"

    # More robust regex
    pattern = re.compile(r"""
        ^(.*?)\s* # Name (non-greedy)
        \(                                       # Opening parenthesis
        ([^,()0-9]+(?:[^,()0-9]+\s)*?)?          # Origin (country name, non-numeric, allows spaces)
        (?:,\s*|\s+)?                            # Separator (comma with optional space, or just space)
        ([\d<>-]{1,}(?:\s*-\s*[\d<>-]{1,})?      # Year info (e.g., 1881, <1896, 1841-1880, 1635- )
           (?:\s*\*.*?)?                         # Optional extra text like *Mayflower
        )?
        \)$                                      # Closing parenthesis
    """, re.VERBOSE)

    match = pattern.match(cell_text.strip())

    if match:
        name = match.group(1).strip().rstrip(',')
        origin = match.group(2).strip() if match.group(2) else None
        year_info = match.group(3).strip() if match.group(3) else None
        
        # Sometimes year info might be captured with origin if no comma
        if origin and not year_info:
            year_match = re.search(r'([\d<>-]{4,}(\s*-\s*[\d<>-]{0,})?)$', origin)
            if year_match:
                year_info = year_match.group(1).strip()
                origin = origin.replace(year_info, "").strip()
        
        if origin and origin.lower() == "native american": # Special case for origin
             year_info = None # Year info might not apply or be present

    else: # No parentheses, just name
        name = cell_text.strip().rstrip(',')
        
    # Fallback for names that might still have trailing commas if not caught by rstrip
    name = name.strip().rstrip(',')

    return {
        "id": cell_id, # Unique ID based on cell_text and position
        "name": name,
        "origin": origin,
        "year_info": year_info,
        "raw_text": cell_text.strip(),
        "father_id": None,
        "mother_id": None
    }

def generate_tree_json(csv_data_string):
    reader = csv.reader(csv_data_string.splitlines())
    raw_rows = list(reader)
    
    # --- Step 1: Create nodes for all individuals ---
    # person_nodes uses a unique key (e.g., original text + row/col) to store person dicts
    person_nodes = {} 
    # cell_to_person_id maps (row, col) to person_id for relationship building
    cell_to_person_id = {} 

    max_cols = 0
    for r, row in enumerate(raw_rows):
        max_cols = max(max_cols, len(row))
        for c, cell_text in enumerate(row):
            if cell_text.strip() and cell_text.strip().lower() not in ["mother?", "father?", "#error!"]:
                # Create a more unique ID if names can repeat
                unique_id = f"{cell_text.strip()}_{r}_{c}" 
                person_data = parse_person_cell(cell_text, unique_id)
                if person_data:
                    person_nodes[unique_id] = person_data
                    cell_to_person_id[(r, c)] = unique_id

    # --- Step 2: Establish Parent-Child Relationships ---
    for r in range(len(raw_rows)):
        for c in range(max_cols):
            child_id = cell_to_person_id.get((r, c))
            if not child_id:
                continue

            # Father is in (r, c+1)
            if c + 1 < max_cols:
                father_id = cell_to_person_id.get((r, c + 1))
                if father_id:
                    person_nodes[child_id]["father_id"] = father_id

                    # Mother is in (r_mom, c+1) where (r_mom, c) is empty
                    # and r_mom is the first such row after r.
                    for r_mom in range(r + 1, len(raw_rows)):
                        # Condition: The 'child' slot for the mother's line must be empty
                        # AND the 'father' (husband) slot should contain the mother.
                        # AND the indentation should align: mother's line starts at col c+1
                        
                        is_child_slot_empty = not cell_to_person_id.get((r_mom, c))
                        
                        # Check alignment: does the mother's entry start at column c+1?
                        # This means all cells before raw_rows[r_mom][c+1] should be empty.
                        aligned = True
                        for prev_c in range(c+1):
                            if raw_rows[r_mom][prev_c].strip():
                                aligned = False
                                break
                        
                        if is_child_slot_empty and aligned:
                            mother_id = cell_to_person_id.get((r_mom, c + 1))
                            if mother_id:
                                person_nodes[child_id]["mother_id"] = mother_id
                                break # Found mother for this child on this father's line

    # --- Step 3: Build Parent-to-Children Map for D3 ---
    children_map = {p_id: [] for p_id in person_nodes}
    all_child_ids = set()
    for p_id, data in person_nodes.items():
        if data["father_id"]:
            children_map.setdefault(data["father_id"], []).append(p_id)
            all_child_ids.add(p_id)
        if data["mother_id"]:
            # Avoid adding child twice if it's already under father,
            # D3 usually wants a child once.
            # However, for distinct mother nodes, it's correct.
            # Check if child already added via father to avoid duplicates if mother and father are different nodes.
            if data["father_id"] and data["mother_id"] != data["father_id"]: # Ensure mother is a different node
                 # Simple approach: add to mother's children list if mother exists
                 children_map.setdefault(data["mother_id"], []).append(p_id)
            elif not data["father_id"] and data["mother_id"]: # only mother known
                 children_map.setdefault(data["mother_id"], []).append(p_id)
            all_child_ids.add(p_id)


    # --- Step 4: Identify the "Me" Node as the Root for D3 ---
    me_node_id = None
    # Try to find "Me" by its specific text. This assumes "Me" is unique or the first one is desired.
    # From your CSV, "Me" was at raw_rows[1][15] (0-indexed from full CSV line)
    # The unique_id for a cell was defined as f"{cell_text.strip()}_{r}_{c}"
    
    # First, try to find "Me" by its exact text from the CSV data.
    # This is more robust if the position can change slightly but text "Me" is constant.
    for p_id, data in person_nodes.items():
        if data["raw_text"].strip().lower() == "me":
            me_node_id = p_id
            print(f"Found 'Me' node by text: ID='{me_node_id}', Name='{data['name']}'")
            break
    
    # If not found by text "Me", try a positional fallback (heuristic for your specific CSV structure)
    if not me_node_id:
        print("Did not find 'Me' by text. Attempting positional fallback for root.")
        # Heuristic: The "Me" node is expected to be in the second actual data row (index 1),
        # and the first non-empty cell in that row, after any initial fully blank columns.
        # This needs to map to the (r,c) used for cell_to_person_id.
        # Let's find the first actual data cell in the row that likely contains "Me".
        # Based on your CSV, "Me" was in raw_rows[1] (0-indexed).
        if len(raw_rows) > 1: # Ensure there's at least a second row.
            me_row_idx = 1 # Assuming "Me" is on the second line of the CSV file.
            first_data_col_in_me_row = -1
            for c_idx, cell_content in enumerate(raw_rows[me_row_idx]):
                if cell_content.strip():
                    first_data_col_in_me_row = c_idx
                    break
            
            if first_data_col_in_me_row != -1:
                me_node_id = cell_to_person_id.get((me_row_idx, first_data_col_in_me_row))
                if me_node_id:
                     print(f"Found potential 'Me' node by position: ID='{me_node_id}', Name='{person_nodes[me_node_id]['name']}'")
                else:
                    print(f"Positional fallback failed: No person ID at ({me_row_idx}, {first_data_col_in_me_row}).")
            else:
                print("Positional fallback failed: Row {me_row_idx} is empty or has no identifiable start.")
        else:
            print("Positional fallback failed: CSV has less than 2 rows.")


    if not me_node_id:
        print("Error: Could not identify 'Me' node as the root. Please check CSV or adjust root finding logic.")
        # As an absolute last resort, pick the first person from cell_to_person_id if any exist
        if cell_to_person_id:
            first_entry_coords = sorted(cell_to_person_id.keys())[0]
            me_node_id = cell_to_person_id[first_entry_coords]
            print(f"Critical Fallback: Using first available person as root: ID='{me_node_id}', Name='{person_nodes[me_node_id]['name']}'")
        else:
            return {"name": "Error: Root 'Me' not found and no data nodes", "id": "error_root", "children": []}


    # --- Step 5: Recursively Build Ancestor Tree from "Me" ---
    # visited_ids is to prevent infinite loops in case of data errors (e.g., circular refs)
    # This set tracks IDs currently in the recursion stack for the current branch.
    
    # We also need a global set of IDs already fully processed into the tree to avoid re-adding 
    # the same ancestor if they appear in multiple places but should be one node.
    # However, for a simple tree from "Me", each ancestor path is unique.
    # If ancestors could marry, then a global 'already_added_to_tree' might be useful.
    # For now, simple recursion stack check.

    memoized_nodes = {} # To store already built subtrees to handle shared ancestors correctly (diamond shapes)

    def build_ancestor_tree_recursive(person_id, recursion_stack_ids):
        if person_id in recursion_stack_ids:
            print(f"Warning: Circular reference detected for ID {person_id}. Breaking loop.")
            # Return a minimal node to indicate the loop but not break the whole tree.
            p_data_loop = person_nodes.get(person_id, {})
            return {"name": f"LOOP: {p_data_loop.get('name', person_id)}", "id": person_id, "details": p_data_loop.get('details', {}), "countryOfOrigin": p_data_loop.get('origin')}

        if person_id in memoized_nodes: # If this ancestor's subtree is already built, return it
            return memoized_nodes[person_id]

        person_data = person_nodes.get(person_id)
        if not person_data:
            print(f"Warning: Person ID {person_id} not found in person_nodes during tree build.")
            return None # Or a minimal error node: {"name": f"Unknown ({person_id})", "id": person_id}


        current_node = {
            "name": person_data["name"],
            "id": person_data["id"], # Use the unique ID generated earlier
            "details": { # Ensure details are properly populated
                "origin": person_data["origin"],
                "year_info": person_data["year_info"],
                "raw": person_data["raw_text"]
            },
            "countryOfOrigin": person_data["origin"],
            "children": [] # Parents will be added here
        }
        
        recursion_stack_ids.add(person_id)

        # Add father as a "child" in the D3 sense for this inverted tree
        if person_data["father_id"]:
            father_node_tree = build_ancestor_tree_recursive(person_data["father_id"], recursion_stack_ids)
            if father_node_tree:
                 current_node["children"].append(father_node_tree)
        
        # Add mother as a "child"
        if person_data["mother_id"]:
            # Ensure mother is not the same as father if IDs somehow got crossed (unlikely with good parsing)
            # The main check is just that mother_id exists and points to a valid node.
            mother_node_tree = build_ancestor_tree_recursive(person_data["mother_id"], recursion_stack_ids)
            if mother_node_tree:
                current_node["children"].append(mother_node_tree)
        
        recursion_stack_ids.remove(person_id)
        memoized_nodes[person_id] = current_node # Memoize the fully built node
        return current_node

    # Build the tree starting from "Me"
    # Initialize the recursion stack for the first call
    initial_recursion_stack = set()
    d3_tree_root = build_ancestor_tree_recursive(me_node_id, initial_recursion_stack)
    
    if not d3_tree_root: # Should not happen if me_node_id is valid
        return {"name": "Error: Failed to build tree from 'Me'", "id": "error_root_build", "children": []}
        
    return d3_tree_root


    # Get the CSV data from the user input
csv_data_string = """,,,,,,,,,,,,,,,,,
Me,Dad,Grandma,Stephen Duggan,"Mary Duggan (Ireland, 1881)",,,,,,,,,,,,,
,,,,"Stephen J Duggan, (Ireland)",,,,,,,,,,,,,
,,,Mary McDonald,"Hugh McDonald (Ireland, <1896)",,,,,,,,,,,,,
,,,,Mother?,,,,,,,,,,,,,
,,Grandpa,Joseph Rubacky (Austria),George Rubacky (Austria 1881),,,,,,,,,,,,,
,,,,Rose Dobrosky (Austria 1881),,,,,,,,,,,,,
,,,Ellen Burns,Peter Burns,"Michael Burns (Ireland, 1841-1880)",,,,,,,,,,,,
,,,,,"Ellen Welsh (Ireland, 1838-1880)",,,,,,,,,,,,
,,,,Catherine Moran,"John Moran (Ireland, <1874)",,,,,,,,,,,,
,,,,,"Mary Donnelly (Ireland, <1874)",,,,,,,,,,,,
,Mom,Grandpa,George Sydney McLean,William James McLean (Scotland via Canada),,,,,,,,,,,,,
,,,,Jessie Rebecca McLeod (Scotland via Canada),,,,,,,,,,,,,
,,,Irene Louise Pond McLean Skehan,John M Pond,Charles Pond,Lyman Pond,John Adams Pond,Eli Pond,Jacob Pond,Jacob Pond,Ephraim Pond,Daniel Pond,"Robert Pond (England, 1612-1627)",,,,
,,,,,,,,,,,,,"Mary Margaret Hawkins (England, 1612-1627)",,,,
,,,,,,,,,,,,Abigail Shepard (England 1627-1646),,,,,
,,,,,,,,,,,Deborah Hawes,Edward Hawes (England),,,,,
,,,,,,,,,,,,Eliony Lombard,"Bernard Lombard (England, <1632)",,,,
,,,,,,,,,,,,,"Mary Jane Clark (England, <1632)",,,,
,,,,,,,,,,Abigail Heath,Joseph Heath,Isaac Heath (England 1625-1650),,,,,
,,,,,,,,,,,,Mary Davis,"Thomas Davis (England, 1622-1650)",,,,
,,,,,,,,,,,,,Christian Coffin (England 1622-,,,,
,,,,,,,,,,,Mary Martha Dow,Stephen Dow,"Thomas Dow (England, 1601-1636)",,,,
,,,,,,,,,,,,,Phebe Fenn Latly (England 1616-1636),,,,
,,,,,,,,,,,,Ann Story,"William Story (England, 1614-1642)",,,,
,,,,,,,,,,,,,"Sarah Foster (England, 1620-1642)",,,,
,,,,,,,,,Sarah Fales,Joseph Fales,John Fales,James Fales (England 1635-1665),,,,,
,,,,,,,,,,,,Ann Brock (England 1627-1693),,,,,
,,,,,,,,,,,Abigail Hawes,,,,,,
,,,,,,,,,,,,,,,,,
,,,,,,,,,,Hannah Pond,John Pond,Daniel Pond,Robert Pond (England 1626-1640),,,,
,,,,,,,,,,,,,Mary Ball (England 1630-1640),,,,
,,,,,,,,,,,,Ann Edwards,Edward Shephard (England <1640),,,,
,,,,,,,,,,,,,Violet Charnould (England <1640)),,,,
,,,,,,,,,,,Rachel Stow,,,,,,
,,,,,,,,,,,,,,,,,
,,,,,,,,Polly Gould,John Gould,,,,,,,,
,,,,,,,,,Mother?,,,,,,,,
,,,,,,,Sarah Sally Turner,Calvin Turner,Ichabod Turner,Stephen Turner,John Turner,,,,,,
,,,,,,,,,,,,,,,,,
,,,,,,,,,,,Sarah Adams,Edward Adams (England 1629-1660),,,,,
,,,,,,,,,,,,Lydia Penniman (England 1634-1660),,,,,
,,,,,,,,,,Judith Fisher,John Fisher,John Fisher (England 1625-1658),,,,,
,,,,,,,,,,,,Elizabeth Boylston (1640-1658),,,,,
,,,,,,,,,,,Mary Metcalf,John Metcalf (England 1622-1647),,,,,
,,,,,,,,,,,,Mary Chickering (1626-1647),,,,,
,,,,,,,,,Susannah Fisher,Samuel Fisher,Ebenezer Fisher,John Guild (England 1616-1645),,,,,
,,,,,,,,,,,,"Elizabeth Crooke (England, 1624-1645)",,,,,
,,,,,,,,,,,Abigail Ellis,"Richard Ellis (England, 1621-1650)",,,,,
,,,,,,,,,,,,Elizabeth French (England 1629-1650),,,,,
,,,,,,,,,,Mercy Fisher,Cornelius Fisher,Cornelius Fisher,Anthony Fisher (England 1628-1632),,,,
,,,,,,,,,,,,,Allce Ellis (England 1628-1632),,,,
,,,,,,,,,,,,Leah Heaton,Nathaniel Heaton (England 1630-1646),,,,
,,,,,,,,,,,,,Elizabeth Wight (1630-1643),,,,
,,,,,,,,,,,Marcy Colburn,Nathaniel Colburn,"Nathaniel Colbern (England, 1611-1639)",,,,
,,,,,,,,,,,,,"Priscilla Clarke (England, 1613-1639)",,,,
,,,,,,,,,,,,Mary Brooks,Gilbert Brooks (England 1633-1649),,,,
,,,,,,,,,,,,,Elizabeth Simmons,"Moses SImmons (Netherlands, 1604-1627)",,,
,,,,,,,,,,,,,,Sarah Chandler (Netherland 1616-1627),,,
,,,,,,,,Sarah Adams,Elijah Adams,Henry Adams,Henry Adams,Henry Adams (England 1610-1643),,,,,
,,,,,,,,,,,,Elizabeth Paine (England 1620-1643),,,,,
,,,,,,,,,,,Prudence Frary,John Frary (England 1631-1657),,,,,
,,,,,,,,,,,,Elizabeth Adams,Henry Adams (England),,,,
,,,,,,,,,,,,,Edith Squire (England),,,,
,,,,,,,,,,Jemima Morse,Joshua Morse,Samuel Morse,Joseph Morse (England 1615-1648),,,,
,,,,,,,,,,,,,Hannah Phillips (1617-1648),,,,
,,,,,,,,,,,,Elizabeth Wood,Nicholas Wood (England 1595-1630),,,,
,,,,,,,,,,,,,Ann Gleason (England 1590-1630),,,,
,,,,,,,,,,,Mary Paine,Samuel Paine,Stephen Paine (England 1626-1654),,,,
,,,,,,,,,,,,,"Lady Hannah Bass (England, 1633)",,,,
,,,,,,,,,,,,Rebecca Sumner,George Sumner (England 1634-1654),,,,
,,,,,,,,,,,,,Mary Baker (England 1642-1654),,,,
,,,,,,,,,Abigail Chenery,Ephraim Chenery,Isaac Chenery,Isaac Chenery,Lambert Chenery (England 1593-1634),,,,
,,,,,,,,,,,,,Dinah Ellis (England 1593-1634),,,,
,,,,,,,,,,,,Elizabeth Gamlyn,Robert Gamblyn (England 1615-1631),,,,
,,,,,,,,,,,,,Elizabeth Mayo (England 1605-1631),,,,
,,,,,,,,,,,Rachel Bullard,Joseph Bullard,George Bullard (England 1607-1639),,,,
,,,,,,,,,,,,,Magdalene George (England 1606-1639),,,,
,,,,,,,,,,,,Sarah Jones,Thomas Jones (England 1602-1629),,,,
,,,,,,,,,,,,,Anne Greenwood (England 1606-1629),,,,
,,,,,,,,,,Hannah Smith,Samuel Smith,John Smith (England),,,,,
,,,,,,,,,,,,Catherine Morill,Isaac Morill (England 1588-1641),,,,
,,,,,,,,,,,,,"Sarah Clement (England, 1601-1641))",,,,
,,,,,,,,,,,Hanna Mason,Ebenezer Mason,Thomas Mason (England 1625-1669),,,,
,,,,,,,,,,,,,Margaret Partridge (England 1628-1653),,,,
,,,,,,,,,,,,Hannah Clark,Benjamin Clark,Joseph Clark (1613-1645),,,
,,,,,,,,,,,,,,Alice Pepper (1623-1645),,,
,,,,,,,,,,,,,Dorcas Morse,Joseph Morse (England 1615-1638),,,
,,,,,,,,,,,,,,Hannah Phillips (England 1616-1638),,,
,,,,,,Betsey Ellis Morey,Benjamin Morey,Benjamin Morey,Benjamin Morey,Jonathan Morey,Jonathan Morey,Roger Morey (England 1610-1634),,,,,
,,,,,,,,,,,,Mary Johnson (England 1614-1634),,,,,
,,,,,,,,,,,Mary Bartlett,Robert Bartlett (England 1603-1627),,,,,
,,,,,,,,,,,,Mary Warren (England 1610-1627),,,,,
,,,,,,,,,,Hannah Bourne,Job Bourne,Richard Bourne (England 1610-1635),,,,,
,,,,,,,,,,,,Bathsheba Hallett (England 1616-1636),,,,,
,,,,,,,,,,,Ruhamah Hallett,Andrew Hallett (England 1615-1643),,,,,
,,,,,,,,,,,,Anne Bessee (England 1620-1636),,,,,
,,,,,,,,,Thankful Swift,William Swift,William Swift (England 1619-1645),,,,,,
,,,,,,,,,,,Ruth Tobey,Thomas Tobey (England 1601-1628),,,,,
,,,,,,,,,,,,Susannah Tobey (England 1601-1628),,,,,
,,,,,,,,,,Elizabeth Thompson,John Thompson (England 1616-1645),,,,,,
,,,,,,,,,,,Mary Cooke,John Cooke (England 1560-1627),,,74.25,,
,,,,,,,,,,,,Alice Freeman (England 1595-1627),,,,,
,,,,,,,,Hannah Besse,Father?,,,,,,,,
,,,,,,,,,Mother?,,,,,,,,
,,,,,,,Deborah Ellis,Perez Ellis,Philip Ellis,Josiah Ellis,Mordecai Ellis,Thomas Ellis,John Ellis (England 1596-1620),,,,
,,,,,,,,,,,,,Ann Benjamin (England 1590-1620),,,,
,,,,,,,,,,,,Susan Lombard,Bernard Lumber (1608-1635),,,,
,,,,,,,,,,,,,"Elinor Lumwife (England, 1595-1635)",,,,
,,,,,,,,,,,Rebecca Clark,Daniel Clark (England 1619-1640),,,,,
,,,,,,,,,,,,"Mary Beane (England, 1625-1640)",,,,,
,,,,,,,,,,Sarah Blackwell,Joshua Blackwell,Michael Blackwell,Michael Blackwell (England 1600-1622),,,,
,,,,,,,,,,,,,Mrs. Michael Blackwell (England 1600-1622),,,,
,,,,,,,,,,,,Desire Burgess,Robert Knowlton (England1585-1620),,,,
,,,,,,,,,,,,,Anne Hill (England 1589-1620),,,,
,,,,,,,,,,,Mercy Fish,Nathaniel Fish (England 1619-1640),,,,,
,,,,,,,,,,,,Lydia Miller,John Miller (England 1604-1629),,,,
,,,,,,,,,,,,,Lydia Combs (England 1610-1629),,,,
,,,,,,,,,Mary Staples,Seth Staples,John Staples,Joseph Staples,"John Staples (England, 1610-1626)",,,,
,,,,,,,,,,,,,Rebecca Borrroridge (England 1615-1626),,,,
,,,,,,,,,,,,Mary Macomber,John Macomber (England 1613-1642),,,,
,,,,,,,,,,,,,Mary Babcock (England 1618-1642),,,,
,,,,,,,,,,,Hannah Leach,Giles Leach,Lawrence Leach (England 1580-1632),,,,
,,,,,,,,,,,,,Elizabeth Mileham (England 1629-1632),,,,
,,,,,,,,,,,,Anne Nokes,Thomas Nokes (England 1610-1634),,,,
,,,,,,,,,,,,,Sarah Thackwell (England 1615-1634),,,,
,,,,,,,,,,Hannah Staples,Ebenezer Standish,Alexander Standish,Myles Standish (1584-1630),,,,
,,,,,,,,,,,,,Barbara Allen (England 1588-1630),,,,
,,,,,,,,,,,,Sarah Alden,John Alden (England 1598-1621),,,,
,,,,,,,,,,,,,Priscilla Mullins (England 1602-1621),,,,
,,,,,,,,,,,Hannah Sturtevant,Samuel Sturtevant,Samuel Sturtevant (England 1625-1640),,,,
,,,,,,,,,,,,,Ann Lee,Robert Lee (England 1600-1625),,,
,,,,,,,,,,,,,,Mary Atwood (England 1606-1625),,,
,,,,,,,,,,,,Mercy Cornish,Thomas Cornish (England 1615-1641),,,,
,,,,,,,,,,,,,Mary Stone (England 1620-1641),,,,
,,,,,,,,Mary Hathaway,Gilbert Hathaway,Ebenezer Hathaway,Ebenezer Hathaway,Abraham Hathaway,John Hathaway,"Nicholas Hathaway (England, 1621-1627)",,,
,,,,,,,,,,,,,,Elizabeth Sheppard (England 1621-1627),,,
,,,,,,,,,,,,,Martha Shepherd,John Shepard (England 1594-1630),,,
,,,,,,,,,,,,,,Frances Kingston (England 1605-1630),,,
,,,,,,,,,,,,Rebecca Wilbore,Shadrach Wilbore (England 1631-1661),,,,
,,,,,,,,,,,,,Mary Dean,Walter Dean (England 1612-1636),,,
,,,,,,,,,,,,,,Eleanor Strong (1613-1636),,,
,,,,,,,,,,,Hannah Shaw,Benjamin Shaw,John Shaw (England 1630-1650),,,,
,,,,,,,,,,,,,Alice Phillips (England 1631-1650),,,,
,,,,,,,,,,,,Hannah Bicknell,John Bicknell (England 1623-1649),,,,
,,,,,,,,,,,,,Mary Porter,Richard Porter (England 1611-1634),,,
,,,,,,,,,,,,,,Ruth Dorcet (England 1615-1634),,,
,,,,,,,,,,Wealthy Gilbert,Nathaniel Gilbert,Thomas Gilbert,Thomas Gilbert (England 1589-1632),,,,
,,,,,,,,,,,,,Joan Combe (England 1613-1632),,,,
,,,,,,,,,,,,Hannah Blake,William Blake (England 1620-1649),,,,
,,,,,,,,,,,,,Anna Lyon (England 1628-1649),,,,
,,,,,,,,,,,Hannah Bradford,Samuel Bradford,William Bradford,Gov. William Bradford (England 1620 *Mayflower),,,
,,,,,,,,,,,,,,Alice Carpenter (1590-1623),,,
,,,,,,,,,,,,,Alice Richards,Thomas Richards (England 1618-1627),,,
,,,,,,,,,,,,,,Welthian Loring (England 1618-1627),,,
,,,,,,,,,,,,Hannah Rogers,John Rogers,John Rogers (England 1627-1631),,,
,,,,,,,,,,,,,,Frances Watson (England 1627-1631),,,
,,,,,,,,,,,,,Elizabeth Peabody,William Peabody (England 1620-1644),,,
,,,,,,,,,,,,,,Elizabeth Alden (England),Father (England),,
,,,,,,,,,,,,,,,Mother (England),,
,,,,,,,,,Elizabeth Williams,Nathaniel Williams,Nathaniel Williams,Nathaniel Williams,Richard Williams (England 1632-1639),,,,
,,,,,,,,,,,,,Frances Deighton (England 1632-1639),,,,
,,,,,,,,,,,,Elizabeth Rogers,Father?,,,,
,,,,,,,,,,,,,Mother?,,,,
,,,,,,,,,,,Lydia King,Philip King,John King (England 1600-1640),,,,
,,,,,,,,,,,,,Mary Blucks (England 1605-1640),,,,
,,,,,,,,,,,,Judith Whitman,John Whitman (England 1625-1628),,,,
,,,,,,,,,,,,,Ruth Whitman (England 1625-1628),,,,
,,,,,,,,,,Mary Atherton,Joshua Atherton,Joshua Atherton,James Atherton (England 1624-1656),,,,
,,,,,,,,,,,,,Hannah Hudson (England 1630-1656),,,,
,,,,,,,,,,,,Mary Gulliver,Anthony Gulliver (England 1619-1641),,,,
,,,,,,,,,,,,,Elinor Kingsley,Stephen Kingsley (England 1624),,,
,,,,,,,,,,,,,,Mary Spaulding (England 1624),,,
,,,,,,,,,,,Elizabeth Leonard,William Leonard,James Leonard,"James Leonard (Wales, 1620-1640)",,,
,,,,,,,,,,,,,,Mary Martin (Wales 1619-1640),,,
,,,,,,,,,,,,,Lydia Gulliver,Anthony Gulliver (England 1619-1641),,,
,,,,,,,,,,,,,,Lydia Kingsley,Stephen Kingsley (England 1624),,
,,,,,,,,,,,,,,,Mary Spaulding (England 1624),,
,,,,,,,,,,,,Elizabeth Taunt (England 1771),,,,,
,,,,,Harriet Lillian Page,Henry Page,Caleb Page,Caleb Page,Reuben Page,Abraham Page,Benjamin Page,John Page (England 1614-1641),,,,,
,,,,,,,,,,,,Mary Marsh (England 1618-1641),,,,,
,,,,,,,,,,,Mary Whittier,Thomas Whittier (England 1620-1646),,,,,
,,,,,,,,,,,,Ruth Green (England 1626-1646),,,,,
,,,,,,,,,,Judith Worthen,Ezekiel Worthen,George Worthen (England 1597-1636),,,,,
,,,,,,,,,,,,Margaret Heywood (England 1593-1636),,,,,
,,,,,,,,,,,Hannah Martin,George Martin (England 1618-1642),,,,,
,,,,,,,,,,,,Susannah North (England 1621-1642),,,,,
,,,,,,,,,Mary Sargent,Timothy Sargent,Charles Sargent,William Sargent,William Sargent (England 1602-1636),,,,
,,,,,,,,,,,,,Elizabeth Perkins (England 1611-1636),,,,
,,,,,,,,,,,,Mary Colby,Anthony Colby (England 1605-1631),,,,
,,,,,,,,,,,,,Susannah Sargent (England 1608-1631),,,,
,,,,,,,,,,,Hannah Foote,Samuel Foote,Pasco Foote (England 1597-1635),,,,
,,,,,,,,,,,,,Margaret Stallion (England 1604-1635),,,,
,,,,,,,,,,,,Hannah Currier,"Richard Currier (Scotland, 1616-1636)",,,,
,,,,,,,,,,,,,Ann Turner (England 1616-1636),,,,
,,,,,,,,,,Mary Williams,Thomas Williams,Joseph Williams,Roger Williams (England 1629-1631),,,,
,,,,,,,,,,,,,Mary Barnard (England 1629-1631),,,,
,,,,,,,,,,,,Lydia Olney,Thomas Olney (England 1629-1645),,,,
,,,,,,,,,,,,,Marie Ashton (England 1629-1645),,,,
,,,,,,,,,,,Mary Lowell,Benjamin Lowell,John Lowell (England 1595-1642),,,,
,,,,,,,,,,,,,Elizabeth Goodale (England 1614-1642),,,,
,,,,,,,,,,,,Ruth Woodman,Edward Woodman (England 1626-1646),,,,
,,,,,,,,,,,,,Joanna Salway (England 1626-1646),,,,
,,,,,,,,Keziah Sawtell,Moses Sawtell,David Sawtell,Zachariah Sawtell,Zachariah Sawtell,Richard Sawtell (England 1627-1634),,,,
,,,,,,,,,,,,,Elizabeth Pople (England 1627-1634),,,,
,,,,,,,,,,,,Elizabeth Harris,John Harris (England 1607-1640),,,,
,,,,,,,,,,,,,Bridget Angier (England 1626-1640),,,,
,,,,,,,,,,,Mary Blood,Nathaniel Blood,Samuel Woods,John Woods (England 1633-1636),,,
,,,,,,,,,,,,,,Mary Woods (England 1633-1636),,,
,,,,,,,,,,,,,Alice Rushton (England),,,,
,,,,,,,,,,,,Hannah Parker,Joseph Parker (England 1622-1650),,,,
,,,,,,,,,,,,,Rose Whitlock (England 1624-1650),,,,
,,,,,,,,,,Elizabeth Keyes,James Keyes,Solomon Keyes (England),,,,,
,,,,,,,,,,,,Frances Grant (England 1630-1653),,,,,
,,,,,,,,,,,Hannah Divoll,John Divoll,John Divoll,,,,
,,,,,,,,,,,,,Sarah Divoll,,,,
,,,,,,,,,,,,Hannah White,John White (England 1627-1647),,,,
,,,,,,,,,,,,,Joanne West (England 1627-1647),,,,
,,,,,,,,,Elizabeth Merriam,Thomas Merriam,Thomas Merriam,Joseph Merriam,Joseph Merriam (England 1623-1629),,,,
,,,,,,,,,,,,,Sarah Goldstone (England 1623-1629),,,,
,,,,,,,,,,,,Sarah Stone (England 1632-1653),,,,,
,,,,,,,,,,,Mary Harwood,Nathaniel Harwood (England 1626-1660),,,,,
,,,,,,,,,,,,Elizabeth Usher,Hezekiah Usher (England 1615-1645),,,,
,,,,,,,,,,,,,Frances Hill (England 1617-1645),,,,
,,,,,,,,,,Tabitha Stone,Samuel Stone,David Stone (England 1622-1647),,,,,
,,,,,,,,,,,,Dorcas Freeman,Thomas Freeman (England 1600-1626),,,,
,,,,,,,,,,,,,Elizabeth Beauchamp (England 1600-1626),,,,
,,,,,,,,,,,Hannah Searle,Nicolas Searle,,,,,
,,,,,,,,,,,,Hannah Searle,,,,,
,,,,,,,Abigail Black,James Black (Scotland 1762-1795),,,,,,,,,
,,,,,,,,Abigail Pollard,Amos Pollard,Thomas Pollard,Thomas Pollard (England 1670-1692),,,,,,
,,,,,,,,,,,Sarah Farmer (England 1669-1692),,,,,,
,,,,,,,,,,Mary Harwood,William Harwood,John Harwood (England 1612-1665),,,,,
,,,,,,,,,,,,Sarah Simonds,William Simonds (England 1612-1643),,,,
,,,,,,,,,,,,,Judith Phippen (England 1618-1643),,,,
,,,,,,,,,,,Esther Perry,Obadiah Perry,William Perry (England 1606-1628),,,,
,,,,,,,,,,,,,Anna Joanna Holland (England 1611-1628),,,,
,,,,,,,,,,,,Ether Hassell,Richard Hassell (England 1622-1636),,,,
,,,,,,,,,,,,,Joan Banks (England 1625-1632),,,,
,,,,,,,,,Miriam Greeley,Moses Greeley,Joseph Greeley,Andrew Greeley (England 1617-1643),,,,,
,,,,,,,,,,,,Mary Moyse,Joseph Moyse (England 1609-1622),,,,
,,,,,,,,,,,,,Hannah Folcord (England 1609-1622),,,,
,,,,,,,,,,,Martha Wilford,Gilbert Wilford,James Wilford (England 1571-1644),,,,
,,,,,,,,,,,,,Anne Newman (England 1575-1644),,,,
,,,,,,,,,,,,Mary Dow,Thomas Dow (England 1601-1636),,,,
,,,,,,,,,,,,,Phebe Latly (England 1617-1636),,,,
,,,,,,,,,,Mehitable Page,Abraham Page,Benjamin Page,John Page (England 1614-1641),,,,
,,,,,,,,,,,,,Mary Marsh (England 1618-1641),,,,
,,,,,,,,,,,,Mary Whittier,Thomas Whittier (England 1620-1646),,,,
,,,,,,,,,,,,,Ruth Green (England 1626-1646),,,,
,,,,,,,,,,,Judith Worthen,Ezekiel Worthen,George Worthen (England 1597-1636),,,,
,,,,,,,,,,,,,Margaret Heywood (England 1593-1636),,,,
,,,,,,,,,,,,Hannah Martin,George Martin (England 1618-1642),,,,
,,,,,,,,,,,,,Susannah North (England 1621-1642),,,,
,,,,,,Melinda Dodge,Daniel Dodge,Winthrop Dodge,Zachariah Dodge,Daniel Dodge,Daniel Dodge,Richard Dodge,Richard Dodge (England 1602-1644),,,,
,,,,,,,,,,,,,Edith Brayne (England 1603-1644),,,,#ERROR!
,,,,,,,,,,,,Mary Eaton,"William Eaton (England, 1623-1641)",,,,
,,,,,,,,,,,,,"Martha Jenkins (England, 1623-1641)",,,,
,,,,,,,,,,,Joanna Burnham,James Burnham,"John Burnham (England, 1618-1650)",,,,
,,,,,,,,,,,,,Anna/Mary Wright (England),,,,
,,,,,,,,,,,,Mary Cogswell,William Cogswell (England 1619-1649),,,,
,,,,,,,,,,,,,Susanna Hawkes,"Adam Hawkes (England, 1605-1630)",,,
,,,,,,,,,,,,,,"Anna Brown (England, 1605-1630)",,,
,,,,,,,,,,Jerusha Herrick,John Herrick,Joseph Herrick,"Henry Herrick (England, 1604-1628)",,,,
,,,,,,,,,,,,,"Editha Laskin(England, 1604-1628)",,,,
,,,,,,,,,,,,Sarah Leach,John Leach (1611-1648),,,,
,,,,,,,,,,,,,Sarah Conant,"Roger Conant (England, 1618-1628)",,,
,,,,,,,,,,,,,,"Sarah Horton  (England, 1618-1628)",,,
,,,,,,,,,,,Anna Woodbury,Peter Woodbury,"Humphrey Woodbury (England, 1607-1635)",,,,
,,,,,,,,,,,,,Elizabeth Hunter (England 1617-1635),,,,
,,,,,,,,,,,,Sarah Dodge,William Dodge (England 1629),,,,
,,,,,,,,,,,,,"Edith Brayne (England, 1629)",,,,
,,,,,,,,,Martha Cleaves,Ebenezer Cleaves,,William Cleaves,"George Cleaves (England, 1620-1638)",,,,
,,,,,,,,,,,,,Joan Price (England 1620-1638),,,,
,,,,,,,,,,,,Sarah Chandler,William Chandler (England 1622-1628),,,,
,,,,,,,,,,,,,Annis Bayford (England 1622-1628),,,,
,,,,,,,,,,,Martha Corey,Giles Corey (England 1610-1650),,,,,
,,,,,,,,,,,,Margaret Devon (England 1610-1650),,,,,
,,,,,,,,,,Sarah Stone,John Stone,Nathaniel Stone,John Stone (England 1563-1630),,,,
,,,,,,,,,,,,,Elinor Cooke (England 1857-1630),,,,
,,,,,,,,,,,,Remember Corning,"Samuel Corning (England, 1616-1635)",,,,
,,,,,,,,,,,,,Elizabeth Huntley (England 1620-1635),,,,
,,,,,,,,,,,Sarah Gale,Edmund Gale,"Edmund Gale (England, 1630-1641)",,,,
,,,,,,,,,,,,,Constance Ireland (England 1630-1641),,,,
,,,,,,,,,,,,Sarah Dixey,William Dixey (England 1607-1643),,,,
,,,,,,,,,,,,,Hannah Collins (England 1614-1643),,,,
,,,,,,,,Mary Perkins,Abner Perkins,Nathaniel Perkins,Nathaniel Perkins,"Thomas Perkins (England, 1628-1660)",,,,,
,,,,,,,,,,,,Frances Beard,Thomas Beard (England 1612-1628),,,,
,,,,,,,,,,,,,Marie Heriman (England 1607-1628),,,,
,,,,,,,,,,,Hannah Tibbetts,Jeremiah Tibbetts (England 1631-1650),,,,,
,,,,,,,,,,,,Mary Jane Canney,Thomas Canney,,,,
,,,,,,,,,,,,,Mary Loame,,,,
,,,,,,,,,,Abigail Carter,Richard Carter,Richard Carter,Richard Carter (England 1624-1647),,,,
,,,,,,,,,,,,,Ann Tayler (England 1624-1647),,,,
,,,,,,,,,,,,Mary Ricord (England),,,,,
,,,,,,,,,,,Elizabeth Arnold,Caleb Arnold,"Gov. Benedict Arnold (England, 1635)",,,,
,,,,,,,,,,,,,"Damaris Westcott (England, 1621-1644)",,,,
,,,,,,,,,,,,Abigail Wilbur,Samuel Wilbur (England 1622-1644),,,,
,,,,,,,,,,,,,Hannah Porter,"John Porter (England, 1588-1630)",,,
,,,,,,,,,,,,,,Mary Endicot (England 1588-1630),,,
,,,,,,,,,Mary Chick,Amos Chick,Richard Chick,Thomas Chick (England 1641-1674),,,,,
,,,,,,,,,,,,Elizabeth Spencer,Thomas Spencer (England 1596-1630),,,,
,,,,,,,,,,,,,Patience Chadbourne (England 1612-1630),,,,
,,,,,,,,,,,Martha Lord,Nathan Lord,Nathan Lord (England 1630-1656),,,,
,,,,,,,,,,,,,Martha Everett,"William Everett (England, 1614-1640)",,,
,,,,,,,,,,,,,,Margery Witham (England 1618-1640),,,
,,,,,,,,,,,,Martha Tozier,Richard Tozier (England 1630-1662),,,,
,,,,,,,,,,,,,Judith Smith,"Henry Smith (England, 1594-1630)",,,
,,,,,,,,,,,,,,"Frances Sanford (England, 1594-1630)",,,
,,,,,,,,,,Bethiah Gould,Joseph Gould,John Gould,Jarvis Gould (England 1605-1644),,,,
,,,,,,,,,,,,,Mary Bates ,"Clement Bates (England, 1620)",,,
,,,,,,,,,,,,,,"Anna Dalrymple (England, 1620)",,,
,,,,,,,,,,,,Mary Crossman,"Robert Crossman (England, 1632-1652)",,,,
,,,,,,,,,,,,,Sarah Kingsbury,Joseph Kingsbury (England 1605-1630),,,
,,,,,,,,,,,,,,"Millicent Ames (England, 1611-1630)",,,
,,,,,,,,,,,Bethiah Furbish,William Furbish (Scotland 1635- ),,,,,
,,,,,,,,,,,,Rebecca Perriman,John Perriman (England 1630-1639),,,,
,,,,,,,,,,,,,Mary Snelling (England 1630-1639),,,,
,,,,,,,Elizabeth Somes,David Sommes,Morris Somes,Timothy Somes,Morris Somes (England 1610-1655),,,,,,
,,,,,,,,,,,Margerie Johnson (England 1614-1655),,,,,,
,,,,,,,,,,Jane Standwood,Philip Stanwood,Philip Stanwood (England 1600-1628),,,,,
,,,,,,,,,,,,Jane Pearce (England 1610-1628),,,,,
,,,,,,,,,,,Jane Whitmarsh,Father?,,,,,
,,,,,,,,,,,,Mother?,,,,,
,,,,,,,,,Lucy Day,Ebenezer Day,Timothy Day,Anthony Day (England 1617-1650),,,,,
,,,,,,,,,,,,"Susanna Ring (England, 1623-1650)",,,,,
,,,,,,,,,,,Pheobe Wildes,"John Wildes (England, 1618-1642)",,,,,
,,,,,,,,,,,,"Priscilla Gould (England, 1628-1642)",,,,,
,,,,,,,,,,Hannah Downing,David Downing,John Downing,"Emanuel Downing (England, 1622-1640)",,,,
,,,,,,,,,,,,,"Lucy Winthrop (England, 1622-1640)",,,,
,,,,,,,,,,,,Mehitable Brabrooke,"Richard Brabrooke (England, 1613-1650)",,,,
,,,,,,,,,,,,,"Alice Ellis (England, 1630-1650)",,,,
,,,,,,,,,,,Susanna Roberts,John Roberts,"Robert Thomas Roberts (England, 1618-1641)",,,,
,,,,,,,,,,,,,"Susan Downing (England, 1622-1641)",,,,
,,,,,,,,,,,,Hannah Bray,"Thomas Bray (England, 1615-1646)",,,,
,,,,,,,,,,,,,"Mary Wilson (England, 1625-1646)",,,,
,,,,,,,,Jennet Hopkins,William Hopkins (Ireland <1735),,,,,,,,
,,,,,,,,,"Mary MacCostra (England, <1735)",,,,,,,,
,,,,Sadie Eliza Light,Alva Light,Jason Light,Andrew Light,Peter Light (Germany 1752-1786),,,,,,,,,
,,,,,,,,Christina Levensaler,Johan Levansaler (Germany 1731-1751),,,,,,,,
,,,,,,,,,Marie Schumann (Germnay 1732-1751),,,,,,,,
,,,,,,,Abigail Leeman,Daniel Leeman,John Leeman,Nathaniel Leeman,"Samuel Leman (England, 1639-1677)",,,,,,
,,,,,,,,,,,"Mary Longley (England, 1656-1677)",,,,,,
,,,,,,,,,,Mary Hutchison,Samuel Hutchinson,Nathaniel Hutchinson,George Hutchinson (England),,,,
,,,,,,,,,,,,,Margaret Lynde,,,,
,,,,,,,,,,,,Sarah Baker,John Baker (England),,,,
,,,,,,,,,,,,,Elizabeth (England),,,,
,,,,,,,,,,,Sarah Root (likely Native),,,,,,
,,,,,,,,,,,,,,,,,
,,,,,,,,,Elizabeth Pillsbury,Henry Pillsbury,William Pillsbury,"William Pillsbury (England, 1605-1656)",,,,,
,,,,,,,,,,,,"Dorothy Crosby (England, 1620-1656)",,,,,
,,,,,,,,,,,Mary Kinne,"Henry Kinne (England, 1623-1659)",,,,,
,,,,,,,,,,,,"Ann Kinne (England, 1629-1659)",,,,,
,,,,,,,,,,Elizabeth Ring,Jarvis Ring,"Robert Ring (England, 1614-1657)",,,,,
,,,,,,,,,,,,Elizabeth Jarvis (England 1618-1657),,,,,
,,,,,,,,,,,Hannah Fowler,Thomas Fowler,"Philip Fowler Jr (England, 1590-1636)",,,,
,,,,,,,,,,,,,"Mary Winslow (England, 1592-1636)",,,,
,,,,,,,,,,,,Hannah Jordan,"Francis Jordan (England, 1610-1636)",,,,
,,,,,,,,,,,,,Jane Wilson,Lambert Wilson (England),,,
,,,,,,,,,,,,,,Wydan Davis (England),,,
,,,,,,,,Martha Gray,Francis Gray,James Gray,"George Gray (Scotland, 1625-1685)",,,,,,
,,,,,,,,,,,"Sarah Cooper (Scotland, 1656-1685)",,,,,,
,,,,,,,,,,Martha Goodwin,Moses Goodwin,Daniel Goodwin (England),,,,,
,,,,,,,,,,,,Margaret Spencer,"Thomas Spencer (England, 1596-1630)",,,,
,,,,,,,,,,,,,"Patience Chadbourne (England, 1612-1630)",,,,
,,,,,,,,,,,Abigail Taylor,John Taylor,"John Taylor (England, 1610-1630)",,,,
,,,,,,,,,,,,,"Elizabeth Nunn (England, 1610-1630)",,,,
,,,,,,,,,,,,Martha Redding,"Thomas Redding (England, 1607-1633)",,,,
,,,,,,,,,,,,,Lady Eleanor Pennoyr (England 1623-1630),,,,
,,,,,,,,,Marcy Bookings,Henry Bookings,Henry Brookings,"Henry Brookings (England), 1603-1641)",,,,,
,,,,,,,,,,,,Louisa Broquin (France 1581-1641),,,,,
,,,,,,,,,,,Sarah Wadleigh,"John Wadleigh (England, 1600-1636)",,,,,
,,,,,,,,,,,,"Mary Marston (England, 1629)",,,,,
,,,,,,,,,,Sarah Young,Rowland Young,Rowland Young (England 1618-1649),,,,,
,,,,,,,,,,,,"Joanna Knight (England, 1638)",,,,,
,,,,,,,,,,,Susanna Matthews,Walter Matthews,Francis Matthews (England 1600-1626),,,,
,,,,,,,,,,,,,"Thomasine Channon (England, 1598-1626)",,,,
,,,,,,,,,,,,Mary Ward,Samuel Ward (England 1600-1630),,,,
,,,,,,,,,,,,,"Mary Hilliard (England, 1595-1626)",,,,
,,,,,,Mary Dodge, Daniel Dodge,Winthrop Dodge,Zachariah Dodge,Daniel Dodge,Daniel Dodge,Richard Dodge,Richard Dodge (England 1602-1644),,,62.97,
,,,,,,,,,,,,,Edith Brayne (England 1603-1644),,,,
,,,,,,,,,,,,Mary Eaton,"William Eaton (England, 1623-1641)",,,,
,,,,,,,,,,,,,"Martha Jenkins (England, 1623-1641)",,,,
,,,,,,,,,,,Joanna Burnham,James Burnham,"John Burnham (England, 1618-1650)",,,,
,,,,,,,,,,,,,Anna/Mary Wright (England),,,,
,,,,,,,,,,,,Mary Cogswell,William Cogswell (England 1619-1649),,,,
,,,,,,,,,,,,,Susanna Hawkes,"Adam Hawkes (England, 1605-1630)",,,
,,,,,,,,,,,,,,"Anna Brown (England, 1605-1630)",,,
,,,,,,,,,,Jerusha Herrick,John Herrick,Joseph Herrick,"Henry Herrick (England, 1604-1628)",,,,
,,,,,,,,,,,,,"Editha Laskin(England, 1604-1628)",,,,
,,,,,,,,,,,,Sarah Leach,John Leach (1611-1648),,,,
,,,,,,,,,,,,,Sarah Conant,"Roger Conant (England, 1618-1628)",,,
,,,,,,,,,,,,,,"Sarah Horton  (England, 1618-1628)",,,
,,,,,,,,,,,Anna Woodbury,Peter Woodbury,"Humphrey Woodbury (England, 1607-1635)",,,,
,,,,,,,,,,,,,Elizabeth Hunter (England 1617-1635),,,,
,,,,,,,,,,,,Sarah Dodge,William Dodge (England 1629),,,,
,,,,,,,,,,,,,"Edith Brayne (England, 1629)",,,,
,,,,,,,,,Martha Cleaves,Ebenezer Cleaves,,William Cleaves,"George Cleaves (England, 1620-1638)",,,,
,,,,,,,,,,,,,Joan Price (England 1620-1638),,,,
,,,,,,,,,,,,Sarah Chandler,William Chandler (England 1622-1628),,,,
,,,,,,,,,,,,,Annis Bayford (England 1622-1628),,,,
,,,,,,,,,,,Martha Corey,Giles Corey (England 1610-1650),,,,,
,,,,,,,,,,,,Margaret Devon (England 1610-1650),,,,,
,,,,,,,,,,Sarah Stone,John Stone,Nathaniel Stone,John Stone (England 1563-1630),,,,
,,,,,,,,,,,,,Elinor Cooke (England 1857-1630),,,,
,,,,,,,,,,,,Remember Corning,"Samuel Corning (England, 1616-1635)",,,,
,,,,,,,,,,,,,Elizabeth Huntley (England 1620-1635),,,,
,,,,,,,,,,,Sarah Gale,Edmund Gale,"Edmund Gale (England, 1630-1641)",,,,
,,,,,,,,,,,,,Constance Ireland (England 1630-1641),,,,
,,,,,,,,,,,,Sarah Dixey,William Dixey (England 1607-1643),,,,
,,,,,,,,,,,,,Hannah Collins (England 1614-1643),,,,
,,,,,,,,Mary Perkins,Abner Perkins,Nathaniel Perkins,Nathaniel Perkins,"Thomas Perkins (England, 1628-1660)",,,,,
,,,,,,,,,,,,Frances Beard,Thomas Beard (England 1612-1628),,,,
,,,,,,,,,,,,,Marie Heriman (England 1607-1628),,,,
,,,,,,,,,,,Hannah Tibbetts,Jeremiah Tibbetts (England 1631-1650),,,,,
,,,,,,,,,,,,Mary Jane Canney,Thomas Canney,,,,
,,,,,,,,,,,,,Mary Loame,,,,
,,,,,,,,,,Abigail Carter,Richard Carter,Richard Carter,Richard Carter (England 1624-1647),,,,
,,,,,,,,,,,,,Ann Tayler (England 1624-1647),,,,
,,,,,,,,,,,,Mary Ricord (England),,,,,
,,,,,,,,,,,Elizabeth Arnold,Caleb Arnold,"Gov. Benedict Arnold (England, 1635)",,,,
,,,,,,,,,,,,,"Damaris Westcott (England, 1621-1644)",,,,
,,,,,,,,,,,,Abigail Wilbur,Samuel Wilbur (England 1622-1644),,,,
,,,,,,,,,,,,,Hannah Porter,"John Porter (England, 1588-1630)",,,
,,,,,,,,,,,,,,Mary Endicot (England 1588-1630),,,
,,,,,,,,,Mary Chick,Amos Chick,Richard Chick,Thomas Chick (England 1641-1674),,,,,
,,,,,,,,,,,,Elizabeth Spencer,Thomas Spencer (England 1596-1630),,,,
,,,,,,,,,,,,,Patience Chadbourne (England 1612-1630),,,,
,,,,,,,,,,,Martha Lord,Nathan Lord,Nathan Lord (England 1630-1656),,,,
,,,,,,,,,,,,,Martha Everett,"William Everett (England, 1614-1640)",,,
,,,,,,,,,,,,,,Margery Witham (England 1618-1640),,,
,,,,,,,,,,,,Martha Tozier,Richard Tozier (England 1630-1662),,,,
,,,,,,,,,,,,,Judith Smith,"Henry Smith (England, 1594-1630)",,,
,,,,,,,,,,,,,,"Frances Sanford (England, 1594-1630)",,,
,,,,,,,,,,Bethiah Gould,Joseph Gould,John Gould,Jarvis Gould (England 1605-1644),,,,
,,,,,,,,,,,,,Mary Bates ,"Clement Bates (England, 1620)",,,
,,,,,,,,,,,,,,"Anna Dalrymple (England, 1620)",,,
,,,,,,,,,,,,Mary Crossman,"Robert Crossman (England, 1632-1652)",,,,
,,,,,,,,,,,,,Sarah Kingsbury,Joseph Kingsbury (England 1605-1630),,,
,,,,,,,,,,,,,,"Millicent Ames (England, 1611-1630)",,,
,,,,,,,,,,,Bethiah Furbish,William Furbish (Scotland 1635- ),,,,,
,,,,,,,,,,,,Rebecca Perriman,John Perriman (England 1630-1639),,,,
,,,,,,,,,,,,,Mary Snelling (England 1630-1639),,,,
,,,,,,,Elizabeth Sommes,David Sommes,Morris Somes,Timothy Somes,Morris Somes (England 1610-1655),,,,,,
,,,,,,,,,,,Margerie Johnson (England 1614-1655),,,,,,
,,,,,,,,,,Jane Standwood,Philip Stanwood,Philip Stanwood (England 1600-1628),,,,,
,,,,,,,,,,,,Jane Pearce (England 1610-1628),,,,,
,,,,,,,,,,,Jane Whitmarsh,Father?,,,,,
,,,,,,,,,,,,Mother?,,,,,
,,,,,,,,,Lucy Day,Ebenezer Day,Timothy Day,Anthony Day (England 1617-1650),,,,,
,,,,,,,,,,,,"Susanna Ring (England, 1623-1650)",,,,,
,,,,,,,,,,,Pheobe Wildes,"John Wildes (England, 1618-1642)",,,,,
,,,,,,,,,,,,"Priscilla Gould (England, 1628-1642)",,,,,
,,,,,,,,,,Hannah Downing,David Downing,John Downing,"Emanuel Downing (England, 1622-1640)",,,,
,,,,,,,,,,,,,"Lucy Winthrop (England, 1622-1640)",,,,
,,,,,,,,,,,,Mehitable Brabrooke,"Richard Brabrooke (England, 1613-1650)",,,,
,,,,,,,,,,,,,"Alice Ellis (England, 1630-1650)",,,,
,,,,,,,,,,,Susanna Roberts,John Roberts,"Robert Thomas Roberts (England, 1618-1641)",,,,
,,,,,,,,,,,,,"Susan Downing (England, 1622-1641)",,,,
,,,,,,,,,,,,Hannah Bray,"Thomas Bray (England, 1615-1646)",,,,
,,,,,,,,,,,,,"Mary Wilson (England, 1625-1646)",,,,
,,,,,,,,Jennet Hopkins,William Hopkins (Ireland <1735),,,,,,,,
,,,,,,,,,"Mary MacCostra (England, <1735)",,,,,,,,
,,,,,Lizena Sidelinger,Charles Sidelinger,Daniel Sidelinger,Charles Sidelinger,"Martin Sidelinger (Germany, 1746-1754)",,,,,,,,
,,,,,,,,,"Maria Eichhorn (Germany, 1746-1754)",,,,,,,,
,,,,,,,,Sarah Smith,"John Schmidt (Germany, 1740-1767)",,,,,,,,
,,,,,,,,,Mary Schott (Germany <1767),,,,,,,,
,,,,,,,Mary Heyer,Conrad Heyer,Johann Heyer (Germany 1736-1749),,,,,,,,
,,,,,,,,,Katerina Heyer (Germany 1736-1749),,,,,,,,
,,,,,,,,Mary Weaver,Johann Weber (Germany),,,,,,,,
,,,,,,,,,Anna Muller (Germany),,,,,,,,
,,,,,,Elizabeth Dow,George Sidelinger,George Sidelinger (Germany 1751-1775),,,,,,,,,
,,,,,,,,Charlotte Rittal (Germany 1755-1775),,,,,,,,,
,,,,,,,Lydia Seiders,Conrad Seiders (Germany 1739-1767),,,,,,,,,
,,,,,,,,Elizabeth Leissner (Germany 1745-1765),,,,,,,,,
,,Hi-Mom,Laverne Cailor,Frank Cailor,Noah Cailor,Andrew Cailor,Father?,,,,,,,,,,
,,,,,,,Mother?,,,,,,,,,,
,,,,,,Magdalena,Father?,,,,,,,,,,
,,,,,,,Mother?,,,,,,,,,,
,,,,,Louisa Whitenburger,Jacob Whittenberger,Adam Whittenberger,John Jacob Whittenberger,"Johann Whittenberger (Germany, 1751)",,,,,,,,
,,,,,,,,,"Anna Stroeher (Germany, 1751)",,,,,,,,
,,,,,,,,Catherine Engel,Johannes Engel,"Melchor Engel (Germany, 1720-1743)",,,,,,,
,,,,,,,,,,"Mary Beyerle (Germany, 1730)",,,,,,,
,,,,,,,,,Margaret Millar,"Philip Conrad Miller (Germany, 1705-1720)",,,,,,,
,,,,,,,,,,"Hannah Brevwins (Germany, 1702-1720)",,,,,,,
,,,,,,,Hannah Stary (Native American),,,,,,,,,,
,,,,,,Lydia Summers,Samuel Summers,Johannes Summers Jr,"John Summers (Switzerland, 1726-1752)",,,,,,,,
,,,,,,,,,"Catherine Nimm (Switzerland, 1749-1752)",,,,,,,,
,,,,,,,,Elizabeth Snyder,"Jacob Snyder (Germany, 1732-1754)",,,,,,,,
,,,,,,,,,Margaret Studebaker (Germany),,,,,,,,
,,,,,,,,,,,,,,,,,
,,,,,,,Elizabeth Stuckey,Samuel Stuckey,Simon Stuckey (Switzerland),,,,,,,,
,,,,,,,,,Barbara Fuchs,Conrad Fuchs (Germany 1738-1739),,,,,,,
,,,,,,,,,,Dorothy Miller (Germany 1738-1739),,,,,,,
,,,,,,,,Catherine Studebaker,Jacob Studebaker,"Peter Studebaker (Germany, 1695-1752)",,,,,,,
,,,,,,,,,,"Susanahh Gibbons (Germany, 1716-1752)",,,,,,,
,,,,,,,,,Mary Snyder,"Jacob Snyder (Germany, 1732-1756)",,,,,,,
,,,,,,,,,,Margaret Mary Studebaker,Peter Studebaker (Germany 1695-1734),,,,,,
,,,,,,,,,,,Anna Margareta Studebaker (Germany 1702-1734),,,,,,
,,,,Emma Mentzer,Amos Mentzer,John Mentzer,Christopher Mentzer,Johann Mentzer,"Johannes Mentzer (Germany, 1704-1741)",,,,,,,,
,,,,,,,,,"Catherine Wyl (Germany, 1704-1741)",,,,,,,,
,,,,,,,,Anna Breidenstein,"Leonhardt Breidenstein (Germany, 1718-1746)",,,,,,,,
,,,,,,,,,Anna Lungel,Johann Beungel (Germany 1700-1721),,,,,,,
,,,,,,,,,,Maria Salome Wagner (Germany 1696-1721),,,,,,,
,,,,,,,Anna Seidner,Christopher Seidner,"Martin Seidner (Germany, 1754)",,,,,,,,
,,,,,,,,,"Margaretha Schotte (Germany, 1754)",,,,,,,,
,,,,,,,,Catherine Miller,Father?,,,,,,,,
,,,,,,,,,Mother?,,,,,,,,
,,,,,,Eliza Buzard,Father?,,,,,,,,,,
,,,,,,,Mother?,,,,,,,,,,
,,,,,Elizabeth Elser,George Elser,George Elser,"Johann Elser (Germany, 1733-1760)",,,,,,,,,
,,,,,,,,Anna Stoever,"John Stoever (Germany, 1707-1738)",,,,,,,,
,,,,,,,,,"Maria Merkling (Germany, 1715-1738)",,,,,,,,
,,,,,,,Catherina Summer,Johannes Summer,"John Summers (Switzerland, 1726-1752)",,,,,,,,
,,,,,,,,,Catherine?,,,,,,,,
,,,,,,,,Maria Schneider,"Jacob Schneider (Germany, 1732-1765)",,,,,,,,
,,,,,,,,,"Margaretha Stutenbecker (Germany, 1734-1765)",,,,,,,,
,,,,,,Maria Robb,Heinrich Robb,Peter Robb,Jacob Robb (Germany),,,,,,,,
,,,,,,,,,Catherine Kraus,,,,,,,,
,,,,,,,,Anna Dunlap,Father?,,,,,,,,
,,,,,,,,,Mother?,,,,,,,,
,,,,,,,Catharine Fink,Hans Fink,Father?,,,,,,,,
,,,,,,,,,Mother?,,,,,,,,
,,,,,,,,Katherine Melhorn,Father?,,,,,,,,
,,,,,,,,,Mother?,,,,,,,,
,,,Ann Rae Miles,Thomas Miles,"John Miles (Wales, 1835-1864)",,,,,,,,,,,,
,,,,,"Ann E. Miles (Wales, 1837-1864)",,,,,,,,,,,,
,,,,Margaret Thomas,"David Thomas (Wales, 1823-1864)",,,,,,,,,,,,
,,,,,"Gavenny Thomas (Wales, 1831-1864)",,,,,,,,,,,,
"""

final_json_tree = generate_tree_json(csv_data_string)

with open('family_tree.json', 'w', encoding='utf-8') as f:
    json.dump(final_json_tree, f, indent=4)

print("family_tree.json has been created.")