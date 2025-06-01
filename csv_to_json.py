import csv
import re
import json
from collections import defaultdict

# Global cache for calculated origins
CALCULATED_ORIGINS_CACHE = {}

def parse_person_cell(person_string, person_id_from_csv):
    """
    Parses the 'Person' column string to extract name, direct origin, and year info.
    """
    if not person_string or person_string.strip().lower() in ["mother?", "father?", "#error!"]:
        # For placeholder names, we still want a node, but with unknown origin.
        return {
            "id": person_id_from_csv, # Use the ID from the CSV
            "name": person_string.strip(),
            "direct_origin_country": None,
            "year_info": None,
            "raw_text": person_string.strip(),
            "parent1_id": None, # Will be populated from CSV columns
            "parent2_id": None, # Will be populated from CSV columns
            "origin_mix": None,
            "origin_mix_calculated": False
        }

    name = person_string.strip()
    parsed_origin_country = None
    year_info = None
    
    pattern = re.compile(r"""
        ^(.*?)\s* # Name (non-greedy)
        \(                                       # Opening parenthesis
        ([^,()0-9]+(?:[^,()0-9]+\s)*?)?          # Origin (country name)
        (?:,\s*|\s+)?                            # Separator
        ([\d<>-]{1,}(?:\s*-\s*[\d<>-]{1,})?      # Year info
           (?:\s*\*.*?)?                         # Optional extra text
        )?
        \)$                                      # Closing parenthesis
    """, re.VERBOSE)
    match = pattern.match(person_string.strip())

    if match:
        name = match.group(1).strip().rstrip(',')
        temp_origin = match.group(2).strip() if match.group(2) else None
        year_info_match = match.group(3).strip() if match.group(3) else None
        
        if temp_origin:
            year_in_origin_match = re.search(r'([\d<>-]{4,}(\s*-\s*[\d<>-]{0,})?)$', temp_origin)
            if year_in_origin_match and not year_info_match:
                potential_year = year_in_origin_match.group(1).strip()
                potential_country = temp_origin.replace(potential_year, "").strip()
                if potential_country and len(potential_country) > 1 and any(c.isalpha() for c in potential_country):
                    parsed_origin_country = potential_country
                    year_info = potential_year
                else:
                    parsed_origin_country = temp_origin
            else:
                parsed_origin_country = temp_origin
        
        if year_info_match: # Prefer year_info from its own regex group if present
            year_info = year_info_match
        
        if year_info: # Clean up year_info
            year_match_strict = re.match(r'([\d<>-]{1,}(\s*-\s*[\d<>-]{1,})?)', year_info)
            if year_match_strict: year_info = year_match_strict.group(1)
            else: year_info = None
    else:
        name = person_string.strip().rstrip(',')
        
    name = name.strip().rstrip(',')

    return {
        "id": person_id_from_csv, # Use the ID from the CSV
        "name": name,
        "direct_origin_country": parsed_origin_country,
        "year_info": year_info,
        "raw_text": person_string.strip(),
        "parent1_id": None, # Will be populated from CSV columns
        "parent2_id": None, # Will be populated from CSV columns
        "origin_mix": None,
        "origin_mix_calculated": False
    }

def get_calculated_origin_mix_recursive(person_id, all_person_nodes, recursion_guard):
    global CALCULATED_ORIGINS_CACHE
    if not person_id: return {"Unknown": 1.0} # Handle blank parent IDs

    if person_id in recursion_guard:
        print(f"Warning: Circular dependency for origin calculation involving ID {person_id}. Treating as Unknown.")
        return {"Unknown": 1.0}
    if person_id in CALCULATED_ORIGINS_CACHE:
        return CALCULATED_ORIGINS_CACHE[person_id]

    person_data = all_person_nodes.get(person_id)
    if not person_data:
        print(f"Warning: Person data for ID {person_id} not found during origin calculation. Treating as Unknown.")
        return {"Unknown": 1.0}

    if person_data.get("origin_mix_calculated", False):
        return person_data.get("origin_mix", {"Unknown": 1.0})

    final_mix = {}
    recursion_guard.add(person_id)

    if person_data.get("direct_origin_country"):
        country = person_data["direct_origin_country"]
        final_mix = {country: 1.0}
    else:
        p1_id = person_data.get("parent1_id")
        p2_id = person_data.get("parent2_id")

        p1_mix = get_calculated_origin_mix_recursive(p1_id, all_person_nodes, recursion_guard) if p1_id else {"Unknown": 1.0}
        p2_mix = get_calculated_origin_mix_recursive(p2_id, all_person_nodes, recursion_guard) if p2_id else {"Unknown": 1.0}
            
        combined_mix = defaultdict(float)
        for country, percentage in p1_mix.items():
            combined_mix[country] += percentage * 0.5
        for country, percentage in p2_mix.items():
            combined_mix[country] += percentage * 0.5
        
        final_mix_dict = {country: perc for country, perc in combined_mix.items() if perc > 0.001}
        current_sum = sum(final_mix_dict.values())

        if not final_mix_dict:
            final_mix = {"Unknown": 1.0}
        elif 0 < current_sum < 0.999: # If sum is off, add remainder to Unknown
            final_mix_dict["Unknown"] = final_mix_dict.get("Unknown", 0.0) + (1.0 - current_sum)
            final_mix = final_mix_dict
        else: # current_sum is close to 1.0 or 0 (if both parents unknown)
            final_mix = final_mix_dict if final_mix_dict else {"Unknown": 1.0}


    person_data["origin_mix"] = final_mix
    person_data["origin_mix_calculated"] = True
    CALCULATED_ORIGINS_CACHE[person_id] = final_mix
    
    recursion_guard.remove(person_id)
    return final_mix

def build_ancestor_tree_recursive_d3(person_id, all_person_nodes, memoized_d3_nodes, recursion_stack_ids):
    if not person_id: return None # Base case for missing parent

    if person_id in recursion_stack_ids:
        print(f"Warning: Circular reference for D3 tree build: {person_id}")
        p_data_loop = all_person_nodes.get(person_id, {})
        return {"name": f"LOOP: {p_data_loop.get('name', person_id)}", "id": person_id} # Minimal node

    if person_id in memoized_d3_nodes:
        return memoized_d3_nodes[person_id]

    person_data = all_person_nodes.get(person_id)
    if not person_data:
        print(f"Warning: Data for person ID '{person_id}' not found when building D3 tree.")
        return None

    current_origin_mix = person_data.get("origin_mix", {"Unknown": 1.0})

    node = {
        "name": person_data["name"],
        "id": person_data["id"], # This is the ID from CSV
        "details": {
            "direct_origin_country": person_data.get("direct_origin_country"),
            "year_info": person_data.get("year_info"),
            "raw": person_data.get("raw_text"),
            "origin_breakdown": current_origin_mix
        },
        "origin_mix": current_origin_mix,
        "countryOfOrigin": person_data.get("direct_origin_country"), # Original single origin, if any
        "children": []
    }
    
    recursion_stack_ids.add(person_id)

    # Add Parent1 as the first "child" in D3 tree
    if person_data.get("parent1_id"):
        parent1_node_tree = build_ancestor_tree_recursive_d3(person_data["parent1_id"], all_person_nodes, memoized_d3_nodes, recursion_stack_ids)
        if parent1_node_tree: node["children"].append(parent1_node_tree)
    
    # Add Parent2 as the second "child"
    if person_data.get("parent2_id"):
        parent2_node_tree = build_ancestor_tree_recursive_d3(person_data["parent2_id"], all_person_nodes, memoized_d3_nodes, recursion_stack_ids)
        if parent2_node_tree: node["children"].append(parent2_node_tree)
    
    recursion_stack_ids.remove(person_id)
    memoized_d3_nodes[person_id] = node
    return node

def generate_tree_json(csv_data_string):
    global CALCULATED_ORIGINS_CACHE
    CALCULATED_ORIGINS_CACHE = {} 

    person_nodes = {} # Keyed by PersonID from CSV

    # Step 1: Read CSV and populate person_nodes with basic info and parent IDs
    print("Step 1: Parsing CSV into flat node structure...")
    # Use io.StringIO to treat the string as a file for csv.DictReader
    import io
    csvfile = io.StringIO(csv_data_string)
    reader = csv.DictReader(csvfile)
    
    for row in reader:
        person_id_csv = row.get("ID", "").strip()
        person_str = row.get("Person", "").strip()
        if not person_id_csv or not person_str: # Skip rows with no ID or Person string
            print(f"Skipping row due to missing ID or Person string: {row}")
            continue

        parsed_data = parse_person_cell(person_str, person_id_csv)
        if parsed_data:
            # Get parent IDs, ensuring they are None if blank string, not ""
            p1_id = row.get("Parent1ID", "").strip()
            p2_id = row.get("Parent2ID", "").strip()
            parsed_data["parent1_id"] = p1_id if p1_id else None
            parsed_data["parent2_id"] = p2_id if p2_id else None
            person_nodes[person_id_csv] = parsed_data
        else:
            print(f"Could not parse person data for row: {row}")

    print(f"Parsed {len(person_nodes)} individuals from CSV.")
    if not person_nodes:
        print("No individuals parsed. Exiting.")
        return {"name": "Error: No individuals parsed from CSV", "id": "error_no_parse"}

    # Step 2: Calculate origin mix for all persons
    print("Step 2: Calculating origin mixes...")
    for p_id_calc in list(person_nodes.keys()): # list() for safe iteration if needed
        if not person_nodes[p_id_calc].get("origin_mix_calculated"):
            get_calculated_origin_mix_recursive(p_id_calc, person_nodes, set())
    print("Finished origin mix calculations.")

    # Step 3: Identify "Me" Node (root for the D3 tree)
    print("Step 3: Identifying 'Me' node...")
    me_node_id = None
    # Try by ID '1' first, as per sample data
    if "1" in person_nodes and person_nodes["1"]["name"].strip().lower() == "me":
        me_node_id = "1"
    else: # Fallback to searching by name "Me"
        for p_id, data in person_nodes.items():
            if data["name"].strip().lower() == "me":
                me_node_id = p_id
                break
    
    if not me_node_id: # If "Me" still not found, pick first ID as a last resort
        if person_nodes:
            me_node_id = sorted(person_nodes.keys())[0] # Requires IDs to be sortable if not numbers
            print(f"Warning: 'Me' not found by ID '1' or name. Defaulting to first parsed ID: {me_node_id}")
        else: # Should have been caught by earlier check
            print("CRITICAL Error: 'Me' node could not be identified and no nodes exist.")
            return {"name": "Error: Root 'Me' not identified", "id": "error_root_critical"}

    print(f"Identified 'Me' node as: {person_nodes[me_node_id]['name']} (ID: {me_node_id})")
    
    # Step 4: Recursively Build Ancestor Tree for D3 from "Me"
    print("Step 4: Building D3 hierarchical tree...")
    memoized_d3_nodes = {} 
    initial_recursion_stack_d3 = set()
    
    d3_tree_root = build_ancestor_tree_recursive_d3(me_node_id, person_nodes, memoized_d3_nodes, initial_recursion_stack_d3)
    
    if not d3_tree_root:
        return {"name": "Error: Failed to build D3 tree from 'Me'", "id": "error_root_build"}
    print("Finished building D3 tree.")
        
    return d3_tree_root

# --- Main execution part of the script ---
if __name__ == "__main__":
    # You will replace this with your actual CSV data string
    csv_data_string = """ID,Person,Parent1ID,Parent1Name,Parent2ID,Parent2Name
1,Me,2,Dad,3,Mom
2,Dad,4,Grandma,5,Grandpa
3,Mom,6,Grandpa,7,Hi-Mom
4,Grandma,8,Stephen Duggan,9,Mary McDonald
5,Grandpa,10,Joseph Rubacky (Austria),11,Ellen Burns
6,Grandpa,12,George Sydney McLean,13,Irene Louise Pond McLean Skehan
7,Hi-Mom,14,Laverne Cailor,15,Ann Rae Miles
8,Stephen Duggan,16,"Mary Duggan (Ireland, 1881)",17,"Stephen J Duggan, (Ireland)"
9,Mary McDonald,18,"Hugh McDonald (Ireland, <1896)",19,Mother?
10,Joseph Rubacky (Austria),20,George Rubacky (Austria 1881),21,Rose Dobrosky (Austria 1881)
11,Ellen Burns,22,Peter Burns,23,Catherine Moran
12,George Sydney McLean,24,William James McLean (Scotland via Canada),25,Jessie Rebecca McLeod (Scotland via Canada)
13,Irene Louise Pond McLean Skehan,26,John M Pond,27,Sadie Eliza Light
14,Laverne Cailor,28,Frank Cailor,29,Emma Mentzer
15,Ann Rae Miles,30,Thomas Miles,31,Margaret Thomas
16,"Mary Duggan (Ireland, 1881)",,,,
17,"Stephen J Duggan, (Ireland)",,,,
18,"Hugh McDonald (Ireland, <1896)",,,,
19,Mother?,,,,
20,George Rubacky (Austria 1881),,,,
21,Rose Dobrosky (Austria 1881),,,,
22,Peter Burns,32,"Michael Burns (Ireland, 1841-1880)",33,"Ellen Welsh (Ireland, 1838-1880)"
23,Catherine Moran,34,"John Moran (Ireland, <1874)",35,"Mary Donnelly (Ireland, <1874)"
24,William James McLean (Scotland via Canada),,,,
25,Jessie Rebecca McLeod (Scotland via Canada),,,,
26,John M Pond,36,Charles Pond,37,Harriet Lillian Page
27,Sadie Eliza Light,38,Alva Light,39,Lizena Sidelinger
28,Frank Cailor,40,Noah Cailor,41,Louisa Whitenburger
29,Emma Mentzer,42,Amos Mentzer,43,Elizabeth Elser
30,Thomas Miles,44,"John Miles (Wales, 1835-1864)",45,"Ann E. Miles (Wales, 1837-1864)"
31,Margaret Thomas,46,"David Thomas (Wales, 1823-1864)",47,"Gavenny Thomas (Wales, 1831-1864)"
32,"Michael Burns (Ireland, 1841-1880)",,,,
33,"Ellen Welsh (Ireland, 1838-1880)",,,,
34,"John Moran (Ireland, <1874)",,,,
35,"Mary Donnelly (Ireland, <1874)",,,,
36,Charles Pond,48,Lyman Pond,49,Betsey Ellis Morey
37,Harriet Lillian Page,50,Henry Page,51,Melinda Dodge
38,Alva Light,52,Jason Light,53,Mary Dodge
39,Lizena Sidelinger,54,Charles Sidelinger,55,Elizabeth Dow
40,Noah Cailor,56,Andrew Cailor,57,Magdalena
41,Louisa Whitenburger,58,Jacob Whittenberger,59,Lydia Summers
42,Amos Mentzer,60,John Mentzer,61,Eliza Buzard
43,Elizabeth Elser,62,George Elser,63,Maria Robb
44,"John Miles (Wales, 1835-1864)",,,,
45,"Ann E. Miles (Wales, 1837-1864)",,,,
46,"David Thomas (Wales, 1823-1864)",,,,
47,"Gavenny Thomas (Wales, 1831-1864)",,,,
48,Lyman Pond,64,John Adams Pond,65,Sarah Sally Turner
49,Betsey Ellis Morey,66,Benjamin Morey,67,Deborah Ellis
50,Henry Page,68,Caleb Page,69,Abigail Black
51,Melinda Dodge,70,Daniel Dodge,71,Elizabeth Somes
52,Jason Light,72,Andrew Light,73,Abigail Leeman
53,Mary Dodge,74, Daniel Dodge,75,Elizabeth Sommes
54,Charles Sidelinger,76,Daniel Sidelinger,77,Mary Heyer
55,Elizabeth Dow,78,George Sidelinger,79,Lydia Seiders
56,Andrew Cailor,80,Father?,81,Mother?
57,Magdalena,82,Father?,83,Mother?
58,Jacob Whittenberger,84,Adam Whittenberger,85,Hannah Stary (Native American)
59,Lydia Summers,86,Samuel Summers,87,Elizabeth Stuckey
60,John Mentzer,88,Christopher Mentzer,89,Anna Seidner
61,Eliza Buzard,90,Father?,91,Mother?
62,George Elser,92,George Elser,93,Catherina Summer
63,Maria Robb,94,Heinrich Robb,95,Catharine Fink
64,John Adams Pond,96,Eli Pond,97,Polly Gould
65,Sarah Sally Turner,98,Calvin Turner,99,Sarah Adams
66,Benjamin Morey,100,Benjamin Morey,101,Hannah Besse
67,Deborah Ellis,102,Perez Ellis,103,Mary Hathaway
68,Caleb Page,104,Caleb Page,105,Keziah Sawtell
69,Abigail Black,106,James Black (Scotland 1762-1795),107,Abigail Pollard
70,Daniel Dodge,108,Winthrop Dodge,109,Mary Perkins
71,Elizabeth Somes,110,David Sommes,111,Jennet Hopkins
72,Andrew Light,112,Peter Light (Germany 1752-1786),113,Christina Levensaler
73,Abigail Leeman,114,Daniel Leeman,115,Martha Gray
74, Daniel Dodge,116,Winthrop Dodge,117,Mary Perkins
75,Elizabeth Sommes,118,David Sommes,119,Jennet Hopkins
76,Daniel Sidelinger,120,Charles Sidelinger,121,Sarah Smith
77,Mary Heyer,122,Conrad Heyer,123,Mary Weaver
78,George Sidelinger,124,George Sidelinger (Germany 1751-1775),125,Charlotte Rittal (Germany 1755-1775)
79,Lydia Seiders,126,Conrad Seiders (Germany 1739-1767),127,Elizabeth Leissner (Germany 1745-1765)
80,Father?,,,,
81,Mother?,,,,
82,Father?,,,,
83,Mother?,,,,
84,Adam Whittenberger,128,John Jacob Whittenberger,129,Catherine Engel
85,Hannah Stary (Native American),,,,
86,Samuel Summers,130,Johannes Summers Jr,131,Elizabeth Snyder
87,Elizabeth Stuckey,132,Samuel Stuckey,133,Catherine Studebaker
88,Christopher Mentzer,134,Johann Mentzer,135,Anna Breidenstein
89,Anna Seidner,136,Christopher Seidner,137,Catherine Miller
90,Father?,,,,
91,Mother?,,,,
92,George Elser,138,"Johann Elser (Germany, 1733-1760)",139,Anna Stoever
93,Catherina Summer,140,Johannes Summer,141,Maria Schneider
94,Heinrich Robb,142,Peter Robb,143,Anna Dunlap
95,Catharine Fink,144,Hans Fink,145,Katherine Melhorn
96,Eli Pond,146,Jacob Pond,147,Sarah Fales
97,Polly Gould,148,John Gould,149,Mother?
98,Calvin Turner,150,Ichabod Turner,151,Susannah Fisher
99,Sarah Adams,152,Elijah Adams,153,Abigail Chenery
100,Benjamin Morey,154,Benjamin Morey,155,Thankful Swift
101,Hannah Besse,156,Father?,157,Mother?
102,Perez Ellis,158,Philip Ellis,159,Mary Staples
103,Mary Hathaway,160,Gilbert Hathaway,161,Elizabeth Williams
104,Caleb Page,162,Reuben Page,163,Mary Sargent
105,Keziah Sawtell,164,Moses Sawtell,165,Elizabeth Merriam
106,James Black (Scotland 1762-1795),,,,
107,Abigail Pollard,166,Amos Pollard,167,Miriam Greeley
108,Winthrop Dodge,168,Zachariah Dodge,169,Martha Cleaves
109,Mary Perkins,170,Abner Perkins,171,Mary Chick
110,David Sommes,172,Morris Somes,173,Lucy Day
111,Jennet Hopkins,174,William Hopkins (Ireland <1735),175,"Mary MacCostra (England, <1735)"
112,Peter Light (Germany 1752-1786),,,,
113,Christina Levensaler,176,Johan Levansaler (Germany 1731-1751),177,Marie Schumann (Germnay 1732-1751)
114,Daniel Leeman,178,John Leeman,179,Elizabeth Pillsbury
115,Martha Gray,180,Francis Gray,181,Marcy Bookings
116,Winthrop Dodge,182,Zachariah Dodge,183,Martha Cleaves
117,Mary Perkins,184,Abner Perkins,185,Mary Chick
118,David Sommes,186,Morris Somes,187,Lucy Day
119,Jennet Hopkins,188,William Hopkins (Ireland <1735),189,"Mary MacCostra (England, <1735)"
120,Charles Sidelinger,190,"Martin Sidelinger (Germany, 1746-1754)",191,"Maria Eichhorn (Germany, 1746-1754)"
121,Sarah Smith,192,"John Schmidt (Germany, 1740-1767)",193,Mary Schott (Germany <1767)
122,Conrad Heyer,194,Johann Heyer (Germany 1736-1749),195,Katerina Heyer (Germany 1736-1749)
123,Mary Weaver,196,Johann Weber (Germany),197,Anna Muller (Germany)
124,George Sidelinger (Germany 1751-1775),,,,
125,Charlotte Rittal (Germany 1755-1775),,,,
126,Conrad Seiders (Germany 1739-1767),,,,
127,Elizabeth Leissner (Germany 1745-1765),,,,
128,John Jacob Whittenberger,198,"Johann Whittenberger (Germany, 1751)",199,"Anna Stroeher (Germany, 1751)"
129,Catherine Engel,200,Johannes Engel,201,Margaret Millar
130,Johannes Summers Jr,202,"John Summers (Switzerland, 1726-1752)",203,"Catherine Nimm (Switzerland, 1749-1752)"
131,Elizabeth Snyder,204,"Jacob Snyder (Germany, 1732-1754)",205,Margaret Studebaker (Germany)
132,Samuel Stuckey,206,Simon Stuckey (Switzerland),207,Barbara Fuchs
133,Catherine Studebaker,208,Jacob Studebaker,209,Mary Snyder
134,Johann Mentzer,210,"Johannes Mentzer (Germany, 1704-1741)",211,"Catherine Wyl (Germany, 1704-1741)"
135,Anna Breidenstein,212,"Leonhardt Breidenstein (Germany, 1718-1746)",213,Anna Lungel
136,Christopher Seidner,214,"Martin Seidner (Germany, 1754)",215,"Margaretha Schotte (Germany, 1754)"
137,Catherine Miller,216,Father?,217,Mother?
138,"Johann Elser (Germany, 1733-1760)",,,,
139,Anna Stoever,218,"John Stoever (Germany, 1707-1738)",219,"Maria Merkling (Germany, 1715-1738)"
140,Johannes Summer,220,"John Summers (Switzerland, 1726-1752)",221,Catherine?
141,Maria Schneider,222,"Jacob Schneider (Germany, 1732-1765)",223,"Margaretha Stutenbecker (Germany, 1734-1765)"
142,Peter Robb,224,Jacob Robb (Germany),225,Catherine Kraus
143,Anna Dunlap,226,Father?,227,Mother?
144,Hans Fink,228,Father?,229,Mother?
145,Katherine Melhorn,230,Father?,231,Mother?
146,Jacob Pond,232,Jacob Pond,233,Abigail Heath
147,Sarah Fales,234,Joseph Fales,235,Hannah Pond
148,John Gould,,,,
149,Mother?,,,,
150,Ichabod Turner,236,Stephen Turner,237,Judith Fisher
151,Susannah Fisher,238,Samuel Fisher,239,Mercy Fisher
152,Elijah Adams,240,Henry Adams,241,Jemima Morse
153,Abigail Chenery,242,Ephraim Chenery,243,Hannah Smith
154,Benjamin Morey,244,Jonathan Morey,245,Hannah Bourne
155,Thankful Swift,246,William Swift,247,Elizabeth Thompson
156,Father?,,,,
157,Mother?,,,,
158,Philip Ellis,248,Josiah Ellis,249,Sarah Blackwell
159,Mary Staples,250,Seth Staples,251,Hannah Staples
160,Gilbert Hathaway,252,Ebenezer Hathaway,253,Wealthy Gilbert
161,Elizabeth Williams,254,Nathaniel Williams,255,Mary Atherton
162,Reuben Page,256,Abraham Page,257,Judith Worthen
163,Mary Sargent,258,Timothy Sargent,259,Mary Williams
164,Moses Sawtell,260,David Sawtell,261,Elizabeth Keyes
165,Elizabeth Merriam,262,Thomas Merriam,263,Tabitha Stone
166,Amos Pollard,264,Thomas Pollard,265,Mary Harwood
167,Miriam Greeley,266,Moses Greeley,267,Mehitable Page
168,Zachariah Dodge,268,Daniel Dodge,269,Jerusha Herrick
169,Martha Cleaves,270,Ebenezer Cleaves,271,Sarah Stone
170,Abner Perkins,272,Nathaniel Perkins,273,Abigail Carter
171,Mary Chick,274,Amos Chick,275,Bethiah Gould
172,Morris Somes,276,Timothy Somes,277,Jane Standwood
173,Lucy Day,278,Ebenezer Day,279,Hannah Downing
174,William Hopkins (Ireland <1735),,,,
175,"Mary MacCostra (England, <1735)",,,,
176,Johan Levansaler (Germany 1731-1751),,,,
177,Marie Schumann (Germnay 1732-1751),,,,
178,John Leeman,280,Nathaniel Leeman,281,Mary Hutchison
179,Elizabeth Pillsbury,282,Henry Pillsbury,283,Elizabeth Ring
180,Francis Gray,284,James Gray,285,Martha Goodwin
181,Marcy Bookings,286,Henry Bookings,287,Sarah Young
182,Zachariah Dodge,288,Daniel Dodge,289,Jerusha Herrick
183,Martha Cleaves,290,Ebenezer Cleaves,291,Sarah Stone
184,Abner Perkins,292,Nathaniel Perkins,293,Abigail Carter
185,Mary Chick,294,Amos Chick,295,Bethiah Gould
186,Morris Somes,296,Timothy Somes,297,Jane Standwood
187,Lucy Day,298,Ebenezer Day,299,Hannah Downing
188,William Hopkins (Ireland <1735),,,,
189,"Mary MacCostra (England, <1735)",,,,
190,"Martin Sidelinger (Germany, 1746-1754)",,,,
191,"Maria Eichhorn (Germany, 1746-1754)",,,,
192,"John Schmidt (Germany, 1740-1767)",,,,
193,Mary Schott (Germany <1767),,,,
194,Johann Heyer (Germany 1736-1749),,,,
195,Katerina Heyer (Germany 1736-1749),,,,
196,Johann Weber (Germany),,,,
197,Anna Muller (Germany),,,,
198,"Johann Whittenberger (Germany, 1751)",,,,
199,"Anna Stroeher (Germany, 1751)",,,,
200,Johannes Engel,300,"Melchor Engel (Germany, 1720-1743)",301,"Mary Beyerle (Germany, 1730)"
201,Margaret Millar,302,"Philip Conrad Miller (Germany, 1705-1720)",303,"Hannah Brevwins (Germany, 1702-1720)"
202,"John Summers (Switzerland, 1726-1752)",,,,
203,"Catherine Nimm (Switzerland, 1749-1752)",,,,
204,"Jacob Snyder (Germany, 1732-1754)",,,,
205,Margaret Studebaker (Germany),,,,
206,Simon Stuckey (Switzerland),,,,
207,Barbara Fuchs,304,Conrad Fuchs (Germany 1738-1739),305,Dorothy Miller (Germany 1738-1739)
208,Jacob Studebaker,306,"Peter Studebaker (Germany, 1695-1752)",307,"Susanahh Gibbons (Germany, 1716-1752)"
209,Mary Snyder,308,"Jacob Snyder (Germany, 1732-1756)",309,Margaret Mary Studebaker
210,"Johannes Mentzer (Germany, 1704-1741)",,,,
211,"Catherine Wyl (Germany, 1704-1741)",,,,
212,"Leonhardt Breidenstein (Germany, 1718-1746)",,,,
213,Anna Lungel,310,Johann Beungel (Germany 1700-1721),311,Maria Salome Wagner (Germany 1696-1721)
214,"Martin Seidner (Germany, 1754)",,,,
215,"Margaretha Schotte (Germany, 1754)",,,,
216,Father?,,,,
217,Mother?,,,,
218,"John Stoever (Germany, 1707-1738)",,,,
219,"Maria Merkling (Germany, 1715-1738)",,,,
220,"John Summers (Switzerland, 1726-1752)",,,,
221,Catherine?,,,,
222,"Jacob Schneider (Germany, 1732-1765)",,,,
223,"Margaretha Stutenbecker (Germany, 1734-1765)",,,,
224,Jacob Robb (Germany),,,,
225,Catherine Kraus,,,,
226,Father?,,,,
227,Mother?,,,,
228,Father?,,,,
229,Mother?,,,,
230,Father?,,,,
231,Mother?,,,,
232,Jacob Pond,312,Ephraim Pond,313,Deborah Hawes
233,Abigail Heath,314,Joseph Heath,315,Mary Martha Dow
234,Joseph Fales,316,John Fales,317,Abigail Hawes
235,Hannah Pond,318,John Pond,319,Rachel Stow
236,Stephen Turner,320,John Turner,321,Sarah Adams
237,Judith Fisher,322,John Fisher,323,Mary Metcalf
238,Samuel Fisher,324,Ebenezer Fisher,325,Abigail Ellis
239,Mercy Fisher,326,Cornelius Fisher,327,Marcy Colburn
240,Henry Adams,328,Henry Adams,329,Prudence Frary
241,Jemima Morse,330,Joshua Morse,331,Mary Paine
242,Ephraim Chenery,332,Isaac Chenery,333,Rachel Bullard
243,Hannah Smith,334,Samuel Smith,335,Hanna Mason
244,Jonathan Morey,336,Jonathan Morey,337,Mary Bartlett
245,Hannah Bourne,338,Job Bourne,339,Ruhamah Hallett
246,William Swift,340,William Swift (England 1619-1645),341,Ruth Tobey
247,Elizabeth Thompson,342,John Thompson (England 1616-1645),343,Mary Cooke
248,Josiah Ellis,344,Mordecai Ellis,345,Rebecca Clark
249,Sarah Blackwell,346,Joshua Blackwell,347,Mercy Fish
250,Seth Staples,348,John Staples,349,Hannah Leach
251,Hannah Staples,350,Ebenezer Standish,351,Hannah Sturtevant
252,Ebenezer Hathaway,352,Ebenezer Hathaway,353,Hannah Shaw
253,Wealthy Gilbert,354,Nathaniel Gilbert,355,Hannah Bradford
254,Nathaniel Williams,356,Nathaniel Williams,357,Lydia King
255,Mary Atherton,358,Joshua Atherton,359,Elizabeth Leonard
256,Abraham Page,360,Benjamin Page,361,Mary Whittier
257,Judith Worthen,362,Ezekiel Worthen,363,Hannah Martin
258,Timothy Sargent,364,Charles Sargent,365,Hannah Foote
259,Mary Williams,366,Thomas Williams,367,Mary Lowell
260,David Sawtell,368,Zachariah Sawtell,369,Mary Blood
261,Elizabeth Keyes,370,James Keyes,371,Hannah Divoll
262,Thomas Merriam,372,Thomas Merriam,373,Mary Harwood
263,Tabitha Stone,374,Samuel Stone,375,Hannah Searle
264,Thomas Pollard,376,Thomas Pollard (England 1670-1692),377,Sarah Farmer (England 1669-1692)
265,Mary Harwood,378,William Harwood,379,Esther Perry
266,Moses Greeley,380,Joseph Greeley,381,Martha Wilford
267,Mehitable Page,382,Abraham Page,383,Judith Worthen
268,Daniel Dodge,384,Daniel Dodge,385,Joanna Burnham
269,Jerusha Herrick,386,John Herrick,387,Anna Woodbury
270,Ebenezer Cleaves,388,Martha Corey,,
271,Sarah Stone,389,John Stone,390,Sarah Gale
272,Nathaniel Perkins,391,Nathaniel Perkins,392,Hannah Tibbetts
273,Abigail Carter,393,Richard Carter,394,Elizabeth Arnold
274,Amos Chick,395,Richard Chick,396,Martha Lord
275,Bethiah Gould,397,Joseph Gould,398,Bethiah Furbish
276,Timothy Somes,399,Morris Somes (England 1610-1655),400,Margerie Johnson (England 1614-1655)
277,Jane Standwood,401,Philip Stanwood,402,Jane Whitmarsh
278,Ebenezer Day,403,Timothy Day,404,Pheobe Wildes
279,Hannah Downing,405,David Downing,406,Susanna Roberts
280,Nathaniel Leeman,407,"Samuel Leman (England, 1639-1677)",408,"Mary Longley (England, 1656-1677)"
281,Mary Hutchison,409,Samuel Hutchinson,410,Sarah Root (likely Native)
282,Henry Pillsbury,411,William Pillsbury,412,Mary Kinne
283,Elizabeth Ring,413,Jarvis Ring,414,Hannah Fowler
284,James Gray,415,"George Gray (Scotland, 1625-1685)",416,"Sarah Cooper (Scotland, 1656-1685)"
285,Martha Goodwin,417,Moses Goodwin,418,Abigail Taylor
286,Henry Bookings,419,Henry Brookings,420,Sarah Wadleigh
287,Sarah Young,421,Rowland Young,422,Susanna Matthews
288,Daniel Dodge,423,Daniel Dodge,424,Joanna Burnham
289,Jerusha Herrick,425,John Herrick,426,Anna Woodbury
290,Ebenezer Cleaves,427,Martha Corey,,
291,Sarah Stone,428,John Stone,429,Sarah Gale
292,Nathaniel Perkins,430,Nathaniel Perkins,431,Hannah Tibbetts
293,Abigail Carter,432,Richard Carter,433,Elizabeth Arnold
294,Amos Chick,434,Richard Chick,435,Martha Lord
295,Bethiah Gould,436,Joseph Gould,437,Bethiah Furbish
296,Timothy Somes,438,Morris Somes (England 1610-1655),439,Margerie Johnson (England 1614-1655)
297,Jane Standwood,440,Philip Stanwood,441,Jane Whitmarsh
298,Ebenezer Day,442,Timothy Day,443,Pheobe Wildes
299,Hannah Downing,444,David Downing,445,Susanna Roberts
300,"Melchor Engel (Germany, 1720-1743)",,,,
301,"Mary Beyerle (Germany, 1730)",,,,
302,"Philip Conrad Miller (Germany, 1705-1720)",,,,
303,"Hannah Brevwins (Germany, 1702-1720)",,,,
304,Conrad Fuchs (Germany 1738-1739),,,,
305,Dorothy Miller (Germany 1738-1739),,,,
306,"Peter Studebaker (Germany, 1695-1752)",,,,
307,"Susanahh Gibbons (Germany, 1716-1752)",,,,
308,"Jacob Snyder (Germany, 1732-1756)",,,,
309,Margaret Mary Studebaker,446,Peter Studebaker (Germany 1695-1734),447,Anna Margareta Studebaker (Germany 1702-1734)
310,Johann Beungel (Germany 1700-1721),,,,
311,Maria Salome Wagner (Germany 1696-1721),,,,
312,Ephraim Pond,449,Daniel Pond,450,Abigail Shepard (England 1627-1646)
313,Deborah Hawes,451,Edward Hawes (England),452,Eliony Lombard
314,Joseph Heath,453,Isaac Heath (England 1625-1650),454,Mary Davis
315,Mary Martha Dow,455,Stephen Dow,456,Ann Story
316,John Fales,457,James Fales (England 1635-1665),458,Ann Brock (England 1627-1693)
317,Abigail Hawes,,,,
318,John Pond,459,Daniel Pond,460,Ann Edwards
319,Rachel Stow,,,,
320,John Turner,,,,
321,Sarah Adams,461,Edward Adams (England 1629-1660),462,Lydia Penniman (England 1634-1660)
322,John Fisher,463,John Fisher (England 1625-1658),464,Elizabeth Boylston (1640-1658)
323,Mary Metcalf,465,John Metcalf (England 1622-1647),466,Mary Chickering (1626-1647)
324,Ebenezer Fisher,467,John Guild (England 1616-1645),468,"Elizabeth Crooke (England, 1624-1645)"
325,Abigail Ellis,469,"Richard Ellis (England, 1621-1650)",470,Elizabeth French (England 1629-1650)
326,Cornelius Fisher,471,Cornelius Fisher,472,Leah Heaton
327,Marcy Colburn,473,Nathaniel Colburn,474,Mary Brooks
328,Henry Adams,475,Henry Adams (England 1610-1643),476,Elizabeth Paine (England 1620-1643)
329,Prudence Frary,477,John Frary (England 1631-1657),478,Elizabeth Adams
330,Joshua Morse,479,Samuel Morse,480,Elizabeth Wood
331,Mary Paine,481,Samuel Paine,482,Rebecca Sumner
332,Isaac Chenery,483,Isaac Chenery,484,Elizabeth Gamlyn
333,Rachel Bullard,485,Joseph Bullard,486,Sarah Jones
334,Samuel Smith,487,John Smith (England),488,Catherine Morill
335,Hanna Mason,489,Ebenezer Mason,490,Hannah Clark
336,Jonathan Morey,491,Roger Morey (England 1610-1634),492,Mary Johnson (England 1614-1634)
337,Mary Bartlett,493,Robert Bartlett (England 1603-1627),494,Mary Warren (England 1610-1627)
338,Job Bourne,495,Richard Bourne (England 1610-1635),496,Bathsheba Hallett (England 1616-1636)
339,Ruhamah Hallett,497,Andrew Hallett (England 1615-1643),498,Anne Bessee (England 1620-1636)
340,William Swift (England 1619-1645),,,,
341,Ruth Tobey,499,Thomas Tobey (England 1601-1628),500,Susannah Tobey (England 1601-1628)
342,John Thompson (England 1616-1645),,,,
343,Mary Cooke,501,John Cooke (England 1560-1627),502,Alice Freeman (England 1595-1627)
344,Mordecai Ellis,503,Thomas Ellis,504,Susan Lombard
345,Rebecca Clark,505,Daniel Clark (England 1619-1640),506,"Mary Beane (England, 1625-1640)"
346,Joshua Blackwell,507,Michael Blackwell,508,Desire Burgess
347,Mercy Fish,509,Nathaniel Fish (England 1619-1640),510,Lydia Miller
348,John Staples,511,Joseph Staples,512,Mary Macomber
349,Hannah Leach,513,Giles Leach,514,Anne Nokes
350,Ebenezer Standish,515,Alexander Standish,516,Sarah Alden
351,Hannah Sturtevant,517,Samuel Sturtevant,518,Mercy Cornish
352,Ebenezer Hathaway,519,Abraham Hathaway,520,Rebecca Wilbore
353,Hannah Shaw,521,Benjamin Shaw,522,Hannah Bicknell
354,Nathaniel Gilbert,523,Thomas Gilbert,524,Hannah Blake
355,Hannah Bradford,525,Samuel Bradford,526,Hannah Rogers
356,Nathaniel Williams,527,Nathaniel Williams,528,Elizabeth Rogers
357,Lydia King,529,Philip King,530,Judith Whitman
358,Joshua Atherton,531,Joshua Atherton,532,Mary Gulliver
359,Elizabeth Leonard,533,William Leonard,534,Elizabeth Taunt (England 1771)
360,Benjamin Page,535,John Page (England 1614-1641),536,Mary Marsh (England 1618-1641)
361,Mary Whittier,537,Thomas Whittier (England 1620-1646),538,Ruth Green (England 1626-1646)
362,Ezekiel Worthen,539,George Worthen (England 1597-1636),540,Margaret Heywood (England 1593-1636)
363,Hannah Martin,541,George Martin (England 1618-1642),542,Susannah North (England 1621-1642)
364,Charles Sargent,543,William Sargent,544,Mary Colby
365,Hannah Foote,545,Samuel Foote,546,Hannah Currier
366,Thomas Williams,547,Joseph Williams,548,Lydia Olney
367,Mary Lowell,549,Benjamin Lowell,550,Ruth Woodman
368,Zachariah Sawtell,551,Zachariah Sawtell,552,Elizabeth Harris
369,Mary Blood,553,Nathaniel Blood,554,Hannah Parker
370,James Keyes,555,Solomon Keyes (England),556,Frances Grant (England 1630-1653)
371,Hannah Divoll,557,John Divoll,558,Hannah White
372,Thomas Merriam,559,Joseph Merriam,560,Sarah Stone (England 1632-1653)
373,Mary Harwood,561,Nathaniel Harwood (England 1626-1660),562,Elizabeth Usher
374,Samuel Stone,563,David Stone (England 1622-1647),564,Dorcas Freeman
375,Hannah Searle,565,Nicolas Searle,566,Hannah Searle
376,Thomas Pollard (England 1670-1692),,,,
377,Sarah Farmer (England 1669-1692),,,,
378,William Harwood,567,John Harwood (England 1612-1665),568,Sarah Simonds
379,Esther Perry,569,Obadiah Perry,570,Ether Hassell
380,Joseph Greeley,571,Andrew Greeley (England 1617-1643),572,Mary Moyse
381,Martha Wilford,573,Gilbert Wilford,574,Mary Dow
382,Abraham Page,575,Benjamin Page,576,Mary Whittier
383,Judith Worthen,577,Ezekiel Worthen,578,Hannah Martin
384,Daniel Dodge,579,Richard Dodge,580,Mary Eaton
385,Joanna Burnham,581,James Burnham,582,Mary Cogswell
386,John Herrick,583,Joseph Herrick,584,Sarah Leach
387,Anna Woodbury,585,Peter Woodbury,586,Sarah Dodge
388,Martha Corey,589,Giles Corey (England 1610-1650),590,Margaret Devon (England 1610-1650)
389,John Stone,591,Nathaniel Stone,592,Remember Corning
390,Sarah Gale,593,Edmund Gale,594,Sarah Dixey
391,Nathaniel Perkins,595,"Thomas Perkins (England, 1628-1660)",596,Frances Beard
392,Hannah Tibbetts,597,Jeremiah Tibbetts (England 1631-1650),598,Mary Jane Canney
393,Richard Carter,599,Richard Carter,600,Mary Ricord (England)
394,Elizabeth Arnold,601,Caleb Arnold,602,Abigail Wilbur
395,Richard Chick,603,Thomas Chick (England 1641-1674),604,Elizabeth Spencer
396,Martha Lord,605,Nathan Lord,606,Martha Tozier
397,Joseph Gould,607,John Gould,608,Mary Crossman
398,Bethiah Furbish,609,William Furbish (Scotland 1635- ),610,Rebecca Perriman
399,Morris Somes (England 1610-1655),,,,
400,Margerie Johnson (England 1614-1655),,,,
401,Philip Stanwood,611,Philip Stanwood (England 1600-1628),612,Jane Pearce (England 1610-1628)
402,Jane Whitmarsh,613,Father?,614,Mother?
403,Timothy Day,615,Anthony Day (England 1617-1650),616,"Susanna Ring (England, 1623-1650)"
404,Pheobe Wildes,617,"John Wildes (England, 1618-1642)",618,"Priscilla Gould (England, 1628-1642)"
405,David Downing,619,John Downing,620,Mehitable Brabrooke
406,Susanna Roberts,621,John Roberts,622,Hannah Bray
407,"Samuel Leman (England, 1639-1677)",,,,
408,"Mary Longley (England, 1656-1677)",,,,
409,Samuel Hutchinson,623,Nathaniel Hutchinson,624,Sarah Baker
410,Sarah Root (likely Native),,,,
411,William Pillsbury,625,"William Pillsbury (England, 1605-1656)",626,"Dorothy Crosby (England, 1620-1656)"
412,Mary Kinne,627,"Henry Kinne (England, 1623-1659)",628,"Ann Kinne (England, 1629-1659)"
413,Jarvis Ring,629,"Robert Ring (England, 1614-1657)",630,Elizabeth Jarvis (England 1618-1657)
414,Hannah Fowler,631,Thomas Fowler,632,Hannah Jordan
415,"George Gray (Scotland, 1625-1685)",,,,
416,"Sarah Cooper (Scotland, 1656-1685)",,,,
417,Moses Goodwin,633,Daniel Goodwin (England),634,Margaret Spencer
418,Abigail Taylor,635,John Taylor,636,Martha Redding
419,Henry Brookings,637,"Henry Brookings (England), 1603-1641)",638,Louisa Broquin (France 1581-1641)
420,Sarah Wadleigh,639,"John Wadleigh (England, 1600-1636)",640,"Mary Marston (England, 1629)"
421,Rowland Young,641,Rowland Young (England 1618-1649),642,"Joanna Knight (England, 1638)"
422,Susanna Matthews,643,Walter Matthews,644,Mary Ward
423,Daniel Dodge,645,Richard Dodge,646,Mary Eaton
424,Joanna Burnham,647,James Burnham,648,Mary Cogswell
425,John Herrick,649,Joseph Herrick,650,Sarah Leach
426,Anna Woodbury,651,Peter Woodbury,652,Sarah Dodge
427,Martha Corey,655,Giles Corey (England 1610-1650),656,Margaret Devon (England 1610-1650)
428,John Stone,657,Nathaniel Stone,658,Remember Corning
429,Sarah Gale,659,Edmund Gale,660,Sarah Dixey
430,Nathaniel Perkins,661,"Thomas Perkins (England, 1628-1660)",662,Frances Beard
431,Hannah Tibbetts,663,Jeremiah Tibbetts (England 1631-1650),664,Mary Jane Canney
432,Richard Carter,665,Richard Carter,666,Mary Ricord (England)
433,Elizabeth Arnold,667,Caleb Arnold,668,Abigail Wilbur
434,Richard Chick,669,Thomas Chick (England 1641-1674),670,Elizabeth Spencer
435,Martha Lord,671,Nathan Lord,672,Martha Tozier
436,Joseph Gould,673,John Gould,674,Mary Crossman
437,Bethiah Furbish,675,William Furbish (Scotland 1635- ),676,Rebecca Perriman
438,Morris Somes (England 1610-1655),,,,
439,Margerie Johnson (England 1614-1655),,,,
440,Philip Stanwood,677,Philip Stanwood (England 1600-1628),678,Jane Pearce (England 1610-1628)
441,Jane Whitmarsh,679,Father?,680,Mother?
442,Timothy Day,681,Anthony Day (England 1617-1650),682,"Susanna Ring (England, 1623-1650)"
443,Pheobe Wildes,683,"John Wildes (England, 1618-1642)",684,"Priscilla Gould (England, 1628-1642)"
444,David Downing,685,John Downing,686,Mehitable Brabrooke
445,Susanna Roberts,687,John Roberts,688,Hannah Bray
446,Peter Studebaker (Germany 1695-1734),,,,
447,Anna Margareta Studebaker (Germany 1702-1734),,,,
448,"It looks like the sheet is empty. Please upload some data, and I can help you analyze it.",,,,
449,Daniel Pond,689,"Robert Pond (England, 1612-1627)",690,"Mary Margaret Hawkins (England, 1612-1627)"
450,Abigail Shepard (England 1627-1646),,,,
451,Edward Hawes (England),,,,
452,Eliony Lombard,691,"Bernard Lombard (England, <1632)",692,"Mary Jane Clark (England, <1632)"
453,Isaac Heath (England 1625-1650),,,,
454,Mary Davis,693,"Thomas Davis (England, 1622-1650)",694,Christian Coffin (England 1622-
455,Stephen Dow,695,"Thomas Dow (England, 1601-1636)",696,Phebe Fenn Latly (England 1616-1636)
456,Ann Story,697,"William Story (England, 1614-1642)",698,"Sarah Foster (England, 1620-1642)"
457,James Fales (England 1635-1665),,,,
458,Ann Brock (England 1627-1693),,,,
459,Daniel Pond,699,Robert Pond (England 1626-1640),700,Mary Ball (England 1630-1640)
460,Ann Edwards,701,Edward Shephard (England <1640),702,Violet Charnould (England <1640))
461,Edward Adams (England 1629-1660),,,,
462,Lydia Penniman (England 1634-1660),,,,
463,John Fisher (England 1625-1658),,,,
464,Elizabeth Boylston (1640-1658),,,,
465,John Metcalf (England 1622-1647),,,,
466,Mary Chickering (1626-1647),,,,
467,John Guild (England 1616-1645),,,,
468,"Elizabeth Crooke (England, 1624-1645)",,,,
469,"Richard Ellis (England, 1621-1650)",,,,
470,Elizabeth French (England 1629-1650),,,,
471,Cornelius Fisher,703,Anthony Fisher (England 1628-1632),704,Allce Ellis (England 1628-1632)
472,Leah Heaton,705,Nathaniel Heaton (England 1630-1646),706,Elizabeth Wight (1630-1643)
473,Nathaniel Colburn,707,"Nathaniel Colbern (England, 1611-1639)",708,"Priscilla Clarke (England, 1613-1639)"
474,Mary Brooks,709,Gilbert Brooks (England 1633-1649),710,Elizabeth Simmons
475,Henry Adams (England 1610-1643),,,,
476,Elizabeth Paine (England 1620-1643),,,,
477,John Frary (England 1631-1657),,,,
478,Elizabeth Adams,711,Henry Adams (England),712,Edith Squire (England)
479,Samuel Morse,713,Joseph Morse (England 1615-1648),714,Hannah Phillips (1617-1648)
480,Elizabeth Wood,715,Nicholas Wood (England 1595-1630),716,Ann Gleason (England 1590-1630)
481,Samuel Paine,717,Stephen Paine (England 1626-1654),718,"Lady Hannah Bass (England, 1633)"
482,Rebecca Sumner,719,George Sumner (England 1634-1654),720,Mary Baker (England 1642-1654)
483,Isaac Chenery,721,Lambert Chenery (England 1593-1634),722,Dinah Ellis (England 1593-1634)
484,Elizabeth Gamlyn,723,Robert Gamblyn (England 1615-1631),724,Elizabeth Mayo (England 1605-1631)
485,Joseph Bullard,725,George Bullard (England 1607-1639),726,Magdalene George (England 1606-1639)
486,Sarah Jones,727,Thomas Jones (England 1602-1629),728,Anne Greenwood (England 1606-1629)
487,John Smith (England),,,,
488,Catherine Morill,729,Isaac Morill (England 1588-1641),730,"Sarah Clement (England, 1601-1641))"
489,Ebenezer Mason,731,Thomas Mason (England 1625-1669),732,Margaret Partridge (England 1628-1653)
490,Hannah Clark,733,Benjamin Clark,734,Dorcas Morse
491,Roger Morey (England 1610-1634),,,,
492,Mary Johnson (England 1614-1634),,,,
493,Robert Bartlett (England 1603-1627),,,,
494,Mary Warren (England 1610-1627),,,,
495,Richard Bourne (England 1610-1635),,,,
496,Bathsheba Hallett (England 1616-1636),,,,
497,Andrew Hallett (England 1615-1643),,,,
498,Anne Bessee (England 1620-1636),,,,
499,Thomas Tobey (England 1601-1628),,,,
500,Susannah Tobey (England 1601-1628),,,,
501,John Cooke (England 1560-1627),,,,
502,Alice Freeman (England 1595-1627),,,,
503,Thomas Ellis,735,John Ellis (England 1596-1620),736,Ann Benjamin (England 1590-1620)
504,Susan Lombard,737,Bernard Lumber (1608-1635),738,"Elinor Lumwife (England, 1595-1635)"
505,Daniel Clark (England 1619-1640),,,,
506,"Mary Beane (England, 1625-1640)",,,,
507,Michael Blackwell,739,Michael Blackwell (England 1600-1622),740,Mrs. Michael Blackwell (England 1600-1622)
508,Desire Burgess,741,Robert Knowlton (England1585-1620),742,Anne Hill (England 1589-1620)
509,Nathaniel Fish (England 1619-1640),,,,
510,Lydia Miller,743,John Miller (England 1604-1629),744,Lydia Combs (England 1610-1629)
511,Joseph Staples,745,"John Staples (England, 1610-1626)",746,Rebecca Borrroridge (England 1615-1626)
512,Mary Macomber,747,John Macomber (England 1613-1642),748,Mary Babcock (England 1618-1642)
513,Giles Leach,749,Lawrence Leach (England 1580-1632),750,Elizabeth Mileham (England 1629-1632)
514,Anne Nokes,751,Thomas Nokes (England 1610-1634),752,Sarah Thackwell (England 1615-1634)
515,Alexander Standish,753,Myles Standish (1584-1630),754,Barbara Allen (England 1588-1630)
516,Sarah Alden,755,John Alden (England 1598-1621),756,Priscilla Mullins (England 1602-1621)
517,Samuel Sturtevant,757,Samuel Sturtevant (England 1625-1640),758,Ann Lee
518,Mercy Cornish,759,Thomas Cornish (England 1615-1641),760,Mary Stone (England 1620-1641)
519,Abraham Hathaway,761,John Hathaway,762,Martha Shepherd
520,Rebecca Wilbore,763,Shadrach Wilbore (England 1631-1661),764,Mary Dean
521,Benjamin Shaw,765,John Shaw (England 1630-1650),766,Alice Phillips (England 1631-1650)
522,Hannah Bicknell,767,John Bicknell (England 1623-1649),768,Mary Porter
523,Thomas Gilbert,769,Thomas Gilbert (England 1589-1632),770,Joan Combe (England 1613-1632)
524,Hannah Blake,771,William Blake (England 1620-1649),772,Anna Lyon (England 1628-1649)
525,Samuel Bradford,773,William Bradford,774,Alice Richards
526,Hannah Rogers,775,John Rogers,776,Elizabeth Peabody
527,Nathaniel Williams,777,Richard Williams (England 1632-1639),778,Frances Deighton (England 1632-1639)
528,Elizabeth Rogers,779,Father?,780,Mother?
529,Philip King,781,John King (England 1600-1640),782,Mary Blucks (England 1605-1640)
530,Judith Whitman,783,John Whitman (England 1625-1628),784,Ruth Whitman (England 1625-1628)
531,Joshua Atherton,785,James Atherton (England 1624-1656),786,Hannah Hudson (England 1630-1656)
532,Mary Gulliver,787,Anthony Gulliver (England 1619-1641),788,Elinor Kingsley
533,William Leonard,789,James Leonard,790,Lydia Gulliver
534,Elizabeth Taunt (England 1771),,,,
535,John Page (England 1614-1641),,,,
536,Mary Marsh (England 1618-1641),,,,
537,Thomas Whittier (England 1620-1646),,,,
538,Ruth Green (England 1626-1646),,,,
539,George Worthen (England 1597-1636),,,,
540,Margaret Heywood (England 1593-1636),,,,
541,George Martin (England 1618-1642),,,,
542,Susannah North (England 1621-1642),,,,
543,William Sargent,791,William Sargent (England 1602-1636),792,Elizabeth Perkins (England 1611-1636)
544,Mary Colby,793,Anthony Colby (England 1605-1631),794,Susannah Sargent (England 1608-1631)
545,Samuel Foote,795,Pasco Foote (England 1597-1635),796,Margaret Stallion (England 1604-1635)
546,Hannah Currier,797,"Richard Currier (Scotland, 1616-1636)",798,Ann Turner (England 1616-1636)
547,Joseph Williams,799,Roger Williams (England 1629-1631),800,Mary Barnard (England 1629-1631)
548,Lydia Olney,801,Thomas Olney (England 1629-1645),802,Marie Ashton (England 1629-1645)
549,Benjamin Lowell,803,John Lowell (England 1595-1642),804,Elizabeth Goodale (England 1614-1642)
550,Ruth Woodman,805,Edward Woodman (England 1626-1646),806,Joanna Salway (England 1626-1646)
551,Zachariah Sawtell,807,Richard Sawtell (England 1627-1634),808,Elizabeth Pople (England 1627-1634)
552,Elizabeth Harris,809,John Harris (England 1607-1640),810,Bridget Angier (England 1626-1640)
553,Nathaniel Blood,811,Samuel Woods,812,Alice Rushton (England)
554,Hannah Parker,813,Joseph Parker (England 1622-1650),814,Rose Whitlock (England 1624-1650)
555,Solomon Keyes (England),,,,
556,Frances Grant (England 1630-1653),,,,
557,John Divoll,815,John Divoll,816,Sarah Divoll
558,Hannah White,817,John White (England 1627-1647),818,Joanne West (England 1627-1647)
559,Joseph Merriam,819,Joseph Merriam (England 1623-1629),820,Sarah Goldstone (England 1623-1629)
560,Sarah Stone (England 1632-1653),,,,
561,Nathaniel Harwood (England 1626-1660),,,,
562,Elizabeth Usher,821,Hezekiah Usher (England 1615-1645),822,Frances Hill (England 1617-1645)
563,David Stone (England 1622-1647),,,,
564,Dorcas Freeman,823,Thomas Freeman (England 1600-1626),824,Elizabeth Beauchamp (England 1600-1626)
565,Nicolas Searle,,,,
566,Hannah Searle,,,,
567,John Harwood (England 1612-1665),,,,
568,Sarah Simonds,825,William Simonds (England 1612-1643),826,Judith Phippen (England 1618-1643)
569,Obadiah Perry,827,William Perry (England 1606-1628),828,Anna Joanna Holland (England 1611-1628)
570,Ether Hassell,829,Richard Hassell (England 1622-1636),830,Joan Banks (England 1625-1632)
571,Andrew Greeley (England 1617-1643),,,,
572,Mary Moyse,831,Joseph Moyse (England 1609-1622),832,Hannah Folcord (England 1609-1622)
573,Gilbert Wilford,833,James Wilford (England 1571-1644),834,Anne Newman (England 1575-1644)
574,Mary Dow,835,Thomas Dow (England 1601-1636),836,Phebe Latly (England 1617-1636)
575,Benjamin Page,837,John Page (England 1614-1641),838,Mary Marsh (England 1618-1641)
576,Mary Whittier,839,Thomas Whittier (England 1620-1646),840,Ruth Green (England 1626-1646)
577,Ezekiel Worthen,841,George Worthen (England 1597-1636),842,Margaret Heywood (England 1593-1636)
578,Hannah Martin,843,George Martin (England 1618-1642),844,Susannah North (England 1621-1642)
579,Richard Dodge,845,Richard Dodge (England 1602-1644),846,Edith Brayne (England 1603-1644)
580,Mary Eaton,847,"William Eaton (England, 1623-1641)",848,"Martha Jenkins (England, 1623-1641)"
581,James Burnham,849,"John Burnham (England, 1618-1650)",850,Anna/Mary Wright (England)
582,Mary Cogswell,851,William Cogswell (England 1619-1649),852,Susanna Hawkes
583,Joseph Herrick,853,"Henry Herrick (England, 1604-1628)",854,"Editha Laskin(England, 1604-1628)"
584,Sarah Leach,855,John Leach (1611-1648),856,Sarah Conant
585,Peter Woodbury,857,"Humphrey Woodbury (England, 1607-1635)",858,Elizabeth Hunter (England 1617-1635)
586,Sarah Dodge,859,William Dodge (England 1629),860,"Edith Brayne (England, 1629)"
587,William Cleaves,861,"George Cleaves (England, 1620-1638)",862,Joan Price (England 1620-1638)
588,Sarah Chandler,863,William Chandler (England 1622-1628),864,Annis Bayford (England 1622-1628)
589,Giles Corey (England 1610-1650),,,,
590,Margaret Devon (England 1610-1650),,,,
591,Nathaniel Stone,865,John Stone (England 1563-1630),866,Elinor Cooke (England 1857-1630)
592,Remember Corning,867,"Samuel Corning (England, 1616-1635)",868,Elizabeth Huntley (England 1620-1635)
593,Edmund Gale,869,"Edmund Gale (England, 1630-1641)",870,Constance Ireland (England 1630-1641)
594,Sarah Dixey,871,William Dixey (England 1607-1643),872,Hannah Collins (England 1614-1643)
595,"Thomas Perkins (England, 1628-1660)",,,,
596,Frances Beard,873,Thomas Beard (England 1612-1628),874,Marie Heriman (England 1607-1628)
597,Jeremiah Tibbetts (England 1631-1650),,,,
598,Mary Jane Canney,875,Thomas Canney,876,Mary Loame
599,Richard Carter,877,Richard Carter (England 1624-1647),878,Ann Tayler (England 1624-1647)
600,Mary Ricord (England),,,,
601,Caleb Arnold,879,"Gov. Benedict Arnold (England, 1635)",880,"Damaris Westcott (England, 1621-1644)"
602,Abigail Wilbur,881,Samuel Wilbur (England 1622-1644),882,Hannah Porter
603,Thomas Chick (England 1641-1674),,,,
604,Elizabeth Spencer,883,Thomas Spencer (England 1596-1630),884,Patience Chadbourne (England 1612-1630)
605,Nathan Lord,885,Nathan Lord (England 1630-1656),886,Martha Everett
606,Martha Tozier,887,Richard Tozier (England 1630-1662),888,Judith Smith
607,John Gould,889,Jarvis Gould (England 1605-1644),890,Mary Bates 
608,Mary Crossman,891,"Robert Crossman (England, 1632-1652)",892,Sarah Kingsbury
609,William Furbish (Scotland 1635- ),,,,
610,Rebecca Perriman,893,John Perriman (England 1630-1639),894,Mary Snelling (England 1630-1639)
611,Philip Stanwood (England 1600-1628),,,,
612,Jane Pearce (England 1610-1628),,,,
613,Father?,,,,
614,Mother?,,,,
615,Anthony Day (England 1617-1650),,,,
616,"Susanna Ring (England, 1623-1650)",,,,
617,"John Wildes (England, 1618-1642)",,,,
618,"Priscilla Gould (England, 1628-1642)",,,,
619,John Downing,895,"Emanuel Downing (England, 1622-1640)",896,"Lucy Winthrop (England, 1622-1640)"
620,Mehitable Brabrooke,897,"Richard Brabrooke (England, 1613-1650)",898,"Alice Ellis (England, 1630-1650)"
621,John Roberts,899,"Robert Thomas Roberts (England, 1618-1641)",900,"Susan Downing (England, 1622-1641)"
622,Hannah Bray,901,"Thomas Bray (England, 1615-1646)",902,"Mary Wilson (England, 1625-1646)"
623,Nathaniel Hutchinson,903,George Hutchinson (England),904,Margaret Lynde
624,Sarah Baker,905,John Baker (England),906,Elizabeth (England)
625,"William Pillsbury (England, 1605-1656)",,,,
626,"Dorothy Crosby (England, 1620-1656)",,,,
627,"Henry Kinne (England, 1623-1659)",,,,
628,"Ann Kinne (England, 1629-1659)",,,,
629,"Robert Ring (England, 1614-1657)",,,,
630,Elizabeth Jarvis (England 1618-1657),,,,
631,Thomas Fowler,907,"Philip Fowler Jr (England, 1590-1636)",908,"Mary Winslow (England, 1592-1636)"
632,Hannah Jordan,909,"Francis Jordan (England, 1610-1636)",910,Jane Wilson
633,Daniel Goodwin (England),,,,
634,Margaret Spencer,911,"Thomas Spencer (England, 1596-1630)",912,"Patience Chadbourne (England, 1612-1630)"
635,John Taylor,913,"John Taylor (England, 1610-1630)",914,"Elizabeth Nunn (England, 1610-1630)"
636,Martha Redding,915,"Thomas Redding (England, 1607-1633)",916,Lady Eleanor Pennoyr (England 1623-1630)
637,"Henry Brookings (England), 1603-1641)",,,,
638,Louisa Broquin (France 1581-1641),,,,
639,"John Wadleigh (England, 1600-1636)",,,,
640,"Mary Marston (England, 1629)",,,,
641,Rowland Young (England 1618-1649),,,,
642,"Joanna Knight (England, 1638)",,,,
643,Walter Matthews,917,Francis Matthews (England 1600-1626),918,"Thomasine Channon (England, 1598-1626)"
644,Mary Ward,919,Samuel Ward (England 1600-1630),920,"Mary Hilliard (England, 1595-1626)"
645,Richard Dodge,921,Richard Dodge (England 1602-1644),922,Edith Brayne (England 1603-1644)
646,Mary Eaton,923,"William Eaton (England, 1623-1641)",924,"Martha Jenkins (England, 1623-1641)"
647,James Burnham,925,"John Burnham (England, 1618-1650)",926,Anna/Mary Wright (England)
648,Mary Cogswell,927,William Cogswell (England 1619-1649),928,Susanna Hawkes
649,Joseph Herrick,929,"Henry Herrick (England, 1604-1628)",930,"Editha Laskin(England, 1604-1628)"
650,Sarah Leach,931,John Leach (1611-1648),932,Sarah Conant
651,Peter Woodbury,933,"Humphrey Woodbury (England, 1607-1635)",934,Elizabeth Hunter (England 1617-1635)
652,Sarah Dodge,935,William Dodge (England 1629),936,"Edith Brayne (England, 1629)"
653,William Cleaves,937,"George Cleaves (England, 1620-1638)",938,Joan Price (England 1620-1638)
654,Sarah Chandler,939,William Chandler (England 1622-1628),940,Annis Bayford (England 1622-1628)
655,Giles Corey (England 1610-1650),,,,
656,Margaret Devon (England 1610-1650),,,,
657,Nathaniel Stone,941,John Stone (England 1563-1630),942,Elinor Cooke (England 1857-1630)
658,Remember Corning,943,"Samuel Corning (England, 1616-1635)",944,Elizabeth Huntley (England 1620-1635)
659,Edmund Gale,945,"Edmund Gale (England, 1630-1641)",946,Constance Ireland (England 1630-1641)
660,Sarah Dixey,947,William Dixey (England 1607-1643),948,Hannah Collins (England 1614-1643)
661,"Thomas Perkins (England, 1628-1660)",,,,
662,Frances Beard,949,Thomas Beard (England 1612-1628),950,Marie Heriman (England 1607-1628)
663,Jeremiah Tibbetts (England 1631-1650),,,,
664,Mary Jane Canney,951,Thomas Canney,952,Mary Loame
665,Richard Carter,953,Richard Carter (England 1624-1647),954,Ann Tayler (England 1624-1647)
666,Mary Ricord (England),,,,
667,Caleb Arnold,955,"Gov. Benedict Arnold (England, 1635)",956,"Damaris Westcott (England, 1621-1644)"
668,Abigail Wilbur,957,Samuel Wilbur (England 1622-1644),958,Hannah Porter
669,Thomas Chick (England 1641-1674),,,,
670,Elizabeth Spencer,959,Thomas Spencer (England 1596-1630),960,Patience Chadbourne (England 1612-1630)
671,Nathan Lord,961,Nathan Lord (England 1630-1656),962,Martha Everett
672,Martha Tozier,963,Richard Tozier (England 1630-1662),964,Judith Smith
673,John Gould,965,Jarvis Gould (England 1605-1644),966,Mary Bates 
674,Mary Crossman,967,"Robert Crossman (England, 1632-1652)",968,Sarah Kingsbury
675,William Furbish (Scotland 1635- ),,,,
676,Rebecca Perriman,969,John Perriman (England 1630-1639),970,Mary Snelling (England 1630-1639)
677,Philip Stanwood (England 1600-1628),,,,
678,Jane Pearce (England 1610-1628),,,,
679,Father?,,,,
680,Mother?,,,,
681,Anthony Day (England 1617-1650),,,,
682,"Susanna Ring (England, 1623-1650)",,,,
683,"John Wildes (England, 1618-1642)",,,,
684,"Priscilla Gould (England, 1628-1642)",,,,
685,John Downing,971,"Emanuel Downing (England, 1622-1640)",972,"Lucy Winthrop (England, 1622-1640)"
686,Mehitable Brabrooke,973,"Richard Brabrooke (England, 1613-1650)",974,"Alice Ellis (England, 1630-1650)"
687,John Roberts,975,"Robert Thomas Roberts (England, 1618-1641)",976,"Susan Downing (England, 1622-1641)"
688,Hannah Bray,977,"Thomas Bray (England, 1615-1646)",978,"Mary Wilson (England, 1625-1646)"
689,"Robert Pond (England, 1612-1627)",,,,
690,"Mary Margaret Hawkins (England, 1612-1627)",,,,
691,"Bernard Lombard (England, <1632)",,,,
692,"Mary Jane Clark (England, <1632)",,,,
693,"Thomas Davis (England, 1622-1650)",,,,
694,Christian Coffin (England 1622-,,,,
695,"Thomas Dow (England, 1601-1636)",,,,
696,Phebe Fenn Latly (England 1616-1636),,,,
697,"William Story (England, 1614-1642)",,,,
698,"Sarah Foster (England, 1620-1642)",,,,
699,Robert Pond (England 1626-1640),,,,
700,Mary Ball (England 1630-1640),,,,
701,Edward Shephard (England <1640),,,,
702,Violet Charnould (England <1640)),,,,
703,Anthony Fisher (England 1628-1632),,,,
704,Allce Ellis (England 1628-1632),,,,
705,Nathaniel Heaton (England 1630-1646),,,,
706,Elizabeth Wight (1630-1643),,,,
707,"Nathaniel Colbern (England, 1611-1639)",,,,
708,"Priscilla Clarke (England, 1613-1639)",,,,
709,Gilbert Brooks (England 1633-1649),,,,
710,Elizabeth Simmons,979,"Moses SImmons (Netherlands, 1604-1627)",980,Sarah Chandler (Netherland 1616-1627)
711,Henry Adams (England),,,,
712,Edith Squire (England),,,,
713,Joseph Morse (England 1615-1648),,,,
714,Hannah Phillips (1617-1648),,,,
715,Nicholas Wood (England 1595-1630),,,,
716,Ann Gleason (England 1590-1630),,,,
717,Stephen Paine (England 1626-1654),,,,
718,"Lady Hannah Bass (England, 1633)",,,,
719,George Sumner (England 1634-1654),,,,
720,Mary Baker (England 1642-1654),,,,
721,Lambert Chenery (England 1593-1634),,,,
722,Dinah Ellis (England 1593-1634),,,,
723,Robert Gamblyn (England 1615-1631),,,,
724,Elizabeth Mayo (England 1605-1631),,,,
725,George Bullard (England 1607-1639),,,,
726,Magdalene George (England 1606-1639),,,,
727,Thomas Jones (England 1602-1629),,,,
728,Anne Greenwood (England 1606-1629),,,,
729,Isaac Morill (England 1588-1641),,,,
730,"Sarah Clement (England, 1601-1641))",,,,
731,Thomas Mason (England 1625-1669),,,,
732,Margaret Partridge (England 1628-1653),,,,
733,Benjamin Clark,981,Joseph Clark (1613-1645),982,Alice Pepper (1623-1645)
734,Dorcas Morse,983,Joseph Morse (England 1615-1638),984,Hannah Phillips (England 1616-1638)
735,John Ellis (England 1596-1620),,,,
736,Ann Benjamin (England 1590-1620),,,,
737,Bernard Lumber (1608-1635),,,,
738,"Elinor Lumwife (England, 1595-1635)",,,,
739,Michael Blackwell (England 1600-1622),,,,
740,Mrs. Michael Blackwell (England 1600-1622),,,,
741,Robert Knowlton (England1585-1620),,,,
742,Anne Hill (England 1589-1620),,,,
743,John Miller (England 1604-1629),,,,
744,Lydia Combs (England 1610-1629),,,,
745,"John Staples (England, 1610-1626)",,,,
746,Rebecca Borrroridge (England 1615-1626),,,,
747,John Macomber (England 1613-1642),,,,
748,Mary Babcock (England 1618-1642),,,,
749,Lawrence Leach (England 1580-1632),,,,
750,Elizabeth Mileham (England 1629-1632),,,,
751,Thomas Nokes (England 1610-1634),,,,
752,Sarah Thackwell (England 1615-1634),,,,
753,Myles Standish (1584-1630),,,,
754,Barbara Allen (England 1588-1630),,,,
755,John Alden (England 1598-1621),,,,
756,Priscilla Mullins (England 1602-1621),,,,
757,Samuel Sturtevant (England 1625-1640),,,,
758,Ann Lee,985,Robert Lee (England 1600-1625),986,Mary Atwood (England 1606-1625)
759,Thomas Cornish (England 1615-1641),,,,
760,Mary Stone (England 1620-1641),,,,
761,John Hathaway,987,"Nicholas Hathaway (England, 1621-1627)",988,Elizabeth Sheppard (England 1621-1627)
762,Martha Shepherd,989,John Shepard (England 1594-1630),990,Frances Kingston (England 1605-1630)
763,Shadrach Wilbore (England 1631-1661),,,,
764,Mary Dean,991,Walter Dean (England 1612-1636),992,Eleanor Strong (1613-1636)
765,John Shaw (England 1630-1650),,,,
766,Alice Phillips (England 1631-1650),,,,
767,John Bicknell (England 1623-1649),,,,
768,Mary Porter,993,Richard Porter (England 1611-1634),994,Ruth Dorcet (England 1615-1634)
769,Thomas Gilbert (England 1589-1632),,,,
770,Joan Combe (England 1613-1632),,,,
771,William Blake (England 1620-1649),,,,
772,Anna Lyon (England 1628-1649),,,,
773,William Bradford,995,Gov. William Bradford (England 1620 *Mayflower),996,Alice Carpenter (1590-1623)
774,Alice Richards,997,Thomas Richards (England 1618-1627),998,Welthian Loring (England 1618-1627)
775,John Rogers,999,John Rogers (England 1627-1631),1000,Frances Watson (England 1627-1631)
776,Elizabeth Peabody,1001,William Peabody (England 1620-1644),1002,Elizabeth Alden (England)
777,Richard Williams (England 1632-1639),,,,
778,Frances Deighton (England 1632-1639),,,,
779,Father?,,,,
780,Mother?,,,,
781,John King (England 1600-1640),,,,
782,Mary Blucks (England 1605-1640),,,,
783,John Whitman (England 1625-1628),,,,
784,Ruth Whitman (England 1625-1628),,,,
785,James Atherton (England 1624-1656),,,,
786,Hannah Hudson (England 1630-1656),,,,
787,Anthony Gulliver (England 1619-1641),,,,
788,Elinor Kingsley,1003,Stephen Kingsley (England 1624),1004,Mary Spaulding (England 1624)
789,James Leonard,1005,"James Leonard (Wales, 1620-1640)",1006,Mary Martin (Wales 1619-1640)
790,Lydia Gulliver,1007,Anthony Gulliver (England 1619-1641),1008,Lydia Kingsley
791,William Sargent (England 1602-1636),,,,
792,Elizabeth Perkins (England 1611-1636),,,,
793,Anthony Colby (England 1605-1631),,,,
794,Susannah Sargent (England 1608-1631),,,,
795,Pasco Foote (England 1597-1635),,,,
796,Margaret Stallion (England 1604-1635),,,,
797,"Richard Currier (Scotland, 1616-1636)",,,,
798,Ann Turner (England 1616-1636),,,,
799,Roger Williams (England 1629-1631),,,,
800,Mary Barnard (England 1629-1631),,,,
801,Thomas Olney (England 1629-1645),,,,
802,Marie Ashton (England 1629-1645),,,,
803,John Lowell (England 1595-1642),,,,
804,Elizabeth Goodale (England 1614-1642),,,,
805,Edward Woodman (England 1626-1646),,,,
806,Joanna Salway (England 1626-1646),,,,
807,Richard Sawtell (England 1627-1634),,,,
808,Elizabeth Pople (England 1627-1634),,,,
809,John Harris (England 1607-1640),,,,
810,Bridget Angier (England 1626-1640),,,,
811,Samuel Woods,1009,John Woods (England 1633-1636),1010,Mary Woods (England 1633-1636)
812,Alice Rushton (England),,,,
813,Joseph Parker (England 1622-1650),,,,
814,Rose Whitlock (England 1624-1650),,,,
815,John Divoll,,,,
816,Sarah Divoll,,,,
817,John White (England 1627-1647),,,,
818,Joanne West (England 1627-1647),,,,
819,Joseph Merriam (England 1623-1629),,,,
820,Sarah Goldstone (England 1623-1629),,,,
821,Hezekiah Usher (England 1615-1645),,,,
822,Frances Hill (England 1617-1645),,,,
823,Thomas Freeman (England 1600-1626),,,,
824,Elizabeth Beauchamp (England 1600-1626),,,,
825,William Simonds (England 1612-1643),,,,
826,Judith Phippen (England 1618-1643),,,,
827,William Perry (England 1606-1628),,,,
828,Anna Joanna Holland (England 1611-1628),,,,
829,Richard Hassell (England 1622-1636),,,,
830,Joan Banks (England 1625-1632),,,,
831,Joseph Moyse (England 1609-1622),,,,
832,Hannah Folcord (England 1609-1622),,,,
833,James Wilford (England 1571-1644),,,,
834,Anne Newman (England 1575-1644),,,,
835,Thomas Dow (England 1601-1636),,,,
836,Phebe Latly (England 1617-1636),,,,
837,John Page (England 1614-1641),,,,
838,Mary Marsh (England 1618-1641),,,,
839,Thomas Whittier (England 1620-1646),,,,
840,Ruth Green (England 1626-1646),,,,
841,George Worthen (England 1597-1636),,,,
842,Margaret Heywood (England 1593-1636),,,,
843,George Martin (England 1618-1642),,,,
844,Susannah North (England 1621-1642),,,,
845,Richard Dodge (England 1602-1644),,,,
846,Edith Brayne (England 1603-1644),,,,
847,"William Eaton (England, 1623-1641)",,,,
848,"Martha Jenkins (England, 1623-1641)",,,,
849,"John Burnham (England, 1618-1650)",,,,
850,Anna/Mary Wright (England),,,,
851,William Cogswell (England 1619-1649),,,,
852,Susanna Hawkes,1011,"Adam Hawkes (England, 1605-1630)",1012,"Anna Brown (England, 1605-1630)"
853,"Henry Herrick (England, 1604-1628)",,,,
854,"Editha Laskin(England, 1604-1628)",,,,
855,John Leach (1611-1648),,,,
856,Sarah Conant,1013,"Roger Conant (England, 1618-1628)",1014,"Sarah Horton  (England, 1618-1628)"
857,"Humphrey Woodbury (England, 1607-1635)",,,,
858,Elizabeth Hunter (England 1617-1635),,,,
859,William Dodge (England 1629),,,,
860,"Edith Brayne (England, 1629)",,,,
861,"George Cleaves (England, 1620-1638)",,,,
862,Joan Price (England 1620-1638),,,,
863,William Chandler (England 1622-1628),,,,
864,Annis Bayford (England 1622-1628),,,,
865,John Stone (England 1563-1630),,,,
866,Elinor Cooke (England 1857-1630),,,,
867,"Samuel Corning (England, 1616-1635)",,,,
868,Elizabeth Huntley (England 1620-1635),,,,
869,"Edmund Gale (England, 1630-1641)",,,,
870,Constance Ireland (England 1630-1641),,,,
871,William Dixey (England 1607-1643),,,,
872,Hannah Collins (England 1614-1643),,,,
873,Thomas Beard (England 1612-1628),,,,
874,Marie Heriman (England 1607-1628),,,,
875,Thomas Canney,,,,
876,Mary Loame,,,,
877,Richard Carter (England 1624-1647),,,,
878,Ann Tayler (England 1624-1647),,,,
879,"Gov. Benedict Arnold (England, 1635)",,,,
880,"Damaris Westcott (England, 1621-1644)",,,,
881,Samuel Wilbur (England 1622-1644),,,,
882,Hannah Porter,1015,"John Porter (England, 1588-1630)",1016,Mary Endicot (England 1588-1630)
883,Thomas Spencer (England 1596-1630),,,,
884,Patience Chadbourne (England 1612-1630),,,,
885,Nathan Lord (England 1630-1656),,,,
886,Martha Everett,1017,"William Everett (England, 1614-1640)",1018,Margery Witham (England 1618-1640)
887,Richard Tozier (England 1630-1662),,,,
888,Judith Smith,1019,"Henry Smith (England, 1594-1630)",1020,"Frances Sanford (England, 1594-1630)"
889,Jarvis Gould (England 1605-1644),,,,
890,Mary Bates ,1021,"Clement Bates (England, 1620)",1022,"Anna Dalrymple (England, 1620)"
891,"Robert Crossman (England, 1632-1652)",,,,
892,Sarah Kingsbury,1023,Joseph Kingsbury (England 1605-1630),1024,"Millicent Ames (England, 1611-1630)"
893,John Perriman (England 1630-1639),,,,
894,Mary Snelling (England 1630-1639),,,,
895,"Emanuel Downing (England, 1622-1640)",,,,
896,"Lucy Winthrop (England, 1622-1640)",,,,
897,"Richard Brabrooke (England, 1613-1650)",,,,
898,"Alice Ellis (England, 1630-1650)",,,,
899,"Robert Thomas Roberts (England, 1618-1641)",,,,
900,"Susan Downing (England, 1622-1641)",,,,
901,"Thomas Bray (England, 1615-1646)",,,,
902,"Mary Wilson (England, 1625-1646)",,,,
903,George Hutchinson (England),,,,
904,Margaret Lynde,,,,
905,John Baker (England),,,,
906,Elizabeth (England),,,,
907,"Philip Fowler Jr (England, 1590-1636)",,,,
908,"Mary Winslow (England, 1592-1636)",,,,
909,"Francis Jordan (England, 1610-1636)",,,,
910,Jane Wilson,1025,Lambert Wilson (England),1026,Wydan Davis (England)
911,"Thomas Spencer (England, 1596-1630)",,,,
912,"Patience Chadbourne (England, 1612-1630)",,,,
913,"John Taylor (England, 1610-1630)",,,,
914,"Elizabeth Nunn (England, 1610-1630)",,,,
915,"Thomas Redding (England, 1607-1633)",,,,
916,Lady Eleanor Pennoyr (England 1623-1630),,,,
917,Francis Matthews (England 1600-1626),,,,
918,"Thomasine Channon (England, 1598-1626)",,,,
919,Samuel Ward (England 1600-1630),,,,
920,"Mary Hilliard (England, 1595-1626)",,,,
921,Richard Dodge (England 1602-1644),,,,
922,Edith Brayne (England 1603-1644),,,,
923,"William Eaton (England, 1623-1641)",,,,
924,"Martha Jenkins (England, 1623-1641)",,,,
925,"John Burnham (England, 1618-1650)",,,,
926,Anna/Mary Wright (England),,,,
927,William Cogswell (England 1619-1649),,,,
928,Susanna Hawkes,1027,"Adam Hawkes (England, 1605-1630)",1028,"Anna Brown (England, 1605-1630)"
929,"Henry Herrick (England, 1604-1628)",,,,
930,"Editha Laskin(England, 1604-1628)",,,,
931,John Leach (1611-1648),,,,
932,Sarah Conant,1029,"Roger Conant (England, 1618-1628)",1030,"Sarah Horton  (England, 1618-1628)"
933,"Humphrey Woodbury (England, 1607-1635)",,,,
934,Elizabeth Hunter (England 1617-1635),,,,
935,William Dodge (England 1629),,,,
936,"Edith Brayne (England, 1629)",,,,
937,"George Cleaves (England, 1620-1638)",,,,
938,Joan Price (England 1620-1638),,,,
939,William Chandler (England 1622-1628),,,,
940,Annis Bayford (England 1622-1628),,,,
941,John Stone (England 1563-1630),,,,
942,Elinor Cooke (England 1857-1630),,,,
943,"Samuel Corning (England, 1616-1635)",,,,
944,Elizabeth Huntley (England 1620-1635),,,,
945,"Edmund Gale (England, 1630-1641)",,,,
946,Constance Ireland (England 1630-1641),,,,
947,William Dixey (England 1607-1643),,,,
948,Hannah Collins (England 1614-1643),,,,
949,Thomas Beard (England 1612-1628),,,,
950,Marie Heriman (England 1607-1628),,,,
951,Thomas Canney,,,,
952,Mary Loame,,,,
953,Richard Carter (England 1624-1647),,,,
954,Ann Tayler (England 1624-1647),,,,
955,"Gov. Benedict Arnold (England, 1635)",,,,
956,"Damaris Westcott (England, 1621-1644)",,,,
957,Samuel Wilbur (England 1622-1644),,,,
958,Hannah Porter,1031,"John Porter (England, 1588-1630)",1032,Mary Endicot (England 1588-1630)
959,Thomas Spencer (England 1596-1630),,,,
960,Patience Chadbourne (England 1612-1630),,,,
961,Nathan Lord (England 1630-1656),,,,
962,Martha Everett,1033,"William Everett (England, 1614-1640)",1034,Margery Witham (England 1618-1640)
963,Richard Tozier (England 1630-1662),,,,
964,Judith Smith,1035,"Henry Smith (England, 1594-1630)",1036,"Frances Sanford (England, 1594-1630)"
965,Jarvis Gould (England 1605-1644),,,,
966,Mary Bates ,1037,"Clement Bates (England, 1620)",1038,"Anna Dalrymple (England, 1620)"
967,"Robert Crossman (England, 1632-1652)",,,,
968,Sarah Kingsbury,1039,Joseph Kingsbury (England 1605-1630),1040,"Millicent Ames (England, 1611-1630)"
969,John Perriman (England 1630-1639),,,,
970,Mary Snelling (England 1630-1639),,,,
971,"Emanuel Downing (England, 1622-1640)",,,,
972,"Lucy Winthrop (England, 1622-1640)",,,,
973,"Richard Brabrooke (England, 1613-1650)",,,,
974,"Alice Ellis (England, 1630-1650)",,,,
975,"Robert Thomas Roberts (England, 1618-1641)",,,,
976,"Susan Downing (England, 1622-1641)",,,,
977,"Thomas Bray (England, 1615-1646)",,,,
978,"Mary Wilson (England, 1625-1646)",,,,
979,"Moses SImmons (Netherlands, 1604-1627)",,,,
980,Sarah Chandler (Netherland 1616-1627),,,,
981,Joseph Clark (1613-1645),,,,
982,Alice Pepper (1623-1645),,,,
983,Joseph Morse (England 1615-1638),,,,
984,Hannah Phillips (England 1616-1638),,,,
985,Robert Lee (England 1600-1625),,,,
986,Mary Atwood (England 1606-1625),,,,
987,"Nicholas Hathaway (England, 1621-1627)",,,,
988,Elizabeth Sheppard (England 1621-1627),,,,
989,John Shepard (England 1594-1630),,,,
990,Frances Kingston (England 1605-1630),,,,
991,Walter Dean (England 1612-1636),,,,
992,Eleanor Strong (1613-1636),,,,
993,Richard Porter (England 1611-1634),,,,
994,Ruth Dorcet (England 1615-1634),,,,
995,Gov. William Bradford (England 1620 *Mayflower),,,,
996,Alice Carpenter (1590-1623),,,,
997,Thomas Richards (England 1618-1627),,,,
998,Welthian Loring (England 1618-1627),,,,
999,John Rogers (England 1627-1631),,,,
1000,Frances Watson (England 1627-1631),,,,
1001,William Peabody (England 1620-1644),,,,
1002,Elizabeth Alden (England),1042,Father (England),1043,Mother (England)
1003,Stephen Kingsley (England 1624),,,,
1004,Mary Spaulding (England 1624),,,,
1005,"James Leonard (Wales, 1620-1640)",,,,
1006,Mary Martin (Wales 1619-1640),,,,
1007,Anthony Gulliver (England 1619-1641),,,,
1008,Lydia Kingsley,1044,Stephen Kingsley (England 1624),1045,Mary Spaulding (England 1624)
1009,John Woods (England 1633-1636),,,,
1010,Mary Woods (England 1633-1636),,,,
1011,"Adam Hawkes (England, 1605-1630)",,,,
1012,"Anna Brown (England, 1605-1630)",,,,
1013,"Roger Conant (England, 1618-1628)",,,,
1014,"Sarah Horton  (England, 1618-1628)",,,,
1015,"John Porter (England, 1588-1630)",,,,
1016,Mary Endicot (England 1588-1630),,,,
1017,"William Everett (England, 1614-1640)",,,,
1018,Margery Witham (England 1618-1640),,,,
1019,"Henry Smith (England, 1594-1630)",,,,
1020,"Frances Sanford (England, 1594-1630)",,,,
1021,"Clement Bates (England, 1620)",,,,
1022,"Anna Dalrymple (England, 1620)",,,,
1023,Joseph Kingsbury (England 1605-1630),,,,
1024,"Millicent Ames (England, 1611-1630)",,,,
1025,Lambert Wilson (England),,,,
1026,Wydan Davis (England),,,,
1027,"Adam Hawkes (England, 1605-1630)",,,,
1028,"Anna Brown (England, 1605-1630)",,,,
1029,"Roger Conant (England, 1618-1628)",,,,
1030,"Sarah Horton  (England, 1618-1628)",,,,
1031,"John Porter (England, 1588-1630)",,,,
1032,Mary Endicot (England 1588-1630),,,,
1033,"William Everett (England, 1614-1640)",,,,
1034,Margery Witham (England 1618-1640),,,,
1035,"Henry Smith (England, 1594-1630)",,,,
1036,"Frances Sanford (England, 1594-1630)",,,,
1037,"Clement Bates (England, 1620)",,,,
1038,"Anna Dalrymple (England, 1620)",,,,
1039,Joseph Kingsbury (England 1605-1630),,,,
1040,"Millicent Ames (England, 1611-1630)",,,,
1042,Father (England),,,,
1043,Mother (England),,,,
1044,Stephen Kingsley (England 1624),,,,
1045,Mary Spaulding (England 1624),,,,
""" # Replace with your actual full CSV data

    family_tree_json_data = generate_tree_json(csv_data_string)
    
    output_filename = 'family_tree_NEW.json' # Use a new name to avoid overwriting
    with open(output_filename, 'w', encoding='utf-8') as f:
       json.dump(family_tree_json_data, f, indent=4)
    print(f"{output_filename} has been created with mixed origins from the flat CSV.")