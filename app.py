import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import pandas as pd
import subprocess
import os

# Helper function to auto-sync SQLite database back to GitHub
def sync_to_github():
    try:
        if "github_token" in st.secrets and "github_repo" in st.secrets:
            token = st.secrets["github_token"]
            repo = st.secrets["github_repo"]
            
            subprocess.run(["git", "config", "--global", "user.email", "streamlit-bot@app.com"], check=True)
            subprocess.run(["git", "config", "--global", "user.name", "Streamlit Bot"], check=True)
            subprocess.run(["git", "add", "traffic_cams.db"], check=True)
            
            commit_res = subprocess.run(["git", "commit", "-m", "Auto-update database [skip ci]"], capture_output=True)
            if commit_res.returncode == 0:
                remote_url = f"https://{token}@github.com/{repo}.git"
                subprocess.run(["git", "push", remote_url, "HEAD:main"], check=True)
    except Exception as e:
        print("Git sync skipped or failed:", e)

# Initialize session state for login
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""

# Auto-login check using query params if "Remember Me" was previously checked
if not st.session_state["logged_in"]:
    qp_logged_in = st.query_params.get("logged_in")
    qp_username = st.query_params.get("username")
    if qp_logged_in == "true" and qp_username:
        st.session_state["logged_in"] = True
        st.session_state["username"] = qp_username

# Login Screen
if not st.session_state["logged_in"]:
    st.title("Login")
    username_input = st.text_input("Your Name / Username")
    pwd = st.text_input("Shared Password", type="password")
    remember_me = st.checkbox("Remember me on this device")
    
    try:
        correct_password = st.secrets["app_password"]
    except Exception:
        correct_password = "SecurePassword123!"
    
    if st.button("Login"):
        if pwd == correct_password and username_input:
            st.session_state["logged_in"] = True
            st.session_state["username"] = username_input
            if remember_me:
                st.query_params["logged_in"] = "true"
                st.query_params["username"] = username_input
            st.rerun()
        elif not username_input:
            st.error("Please enter your name.")
        else:
            st.error("Incorrect password.")
    st.stop()

# Main App Layout with Top Bar for User & Logout
col_title, col_logout = st.columns([4, 1])
with col_title:
    st.title("Traffic Camera Monitor")
    st.write(f"Logged in as: **{st.session_state['username']}**")
with col_logout:
    st.write("") 
    if st.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""
        st.query_params.clear()
        st.rerun()

st.divider()

# Safe Database Connection and Initialization
conn = sqlite3.connect('traffic_cams.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS cameras 
             (id INTEGER PRIMARY KEY, name TEXT, location TEXT, coordinates TEXT, url TEXT, traffic_vision_link TEXT, rating TEXT, submitted_by TEXT, link_to_id INTEGER, position TEXT)''')
conn.commit()

# Robust column verification using PRAGMA
c.execute("PRAGMA table_info(cameras)")
existing_columns = [col[1] for col in c.fetchall()]

if "traffic_vision_link" not in existing_columns:
    c.execute("ALTER TABLE cameras ADD COLUMN traffic_vision_link TEXT")
    conn.commit()

if "submitted_by" not in existing_columns:
    c.execute("ALTER TABLE cameras ADD COLUMN submitted_by TEXT")
    conn.commit()

if "link_to_id" not in existing_columns:
    c.execute("ALTER TABLE cameras ADD COLUMN link_to_id INTEGER")
    conn.commit()

if "position" not in existing_columns:
    c.execute("ALTER TABLE cameras ADD COLUMN position TEXT")
    conn.commit()

# Sidebar Manager (Add, Edit, or Link Tree)
with st.sidebar:
    st.header("Camera Manager")
    action = st.radio("Choose Action", ["Add New Camera", "Edit Existing Camera", "Link Nearby Cam (Tree)"])
    
    ratings_list = ["Green 🟢", "Orange 🟠", "Red 🔴"]

    if action == "Add New Camera":
        with st.form("add_form"):
            name = st.text_input("Camera Name")
            loc = st.text_input("Location")
            coords = st.text_input("Coordinates (e.g., 57.78, 14.16)")
            url = st.text_input("Stream URL")
            vision_link = st.text_input("Traffic Vision Link (URL)")
            rating = st.selectbox("Rating", ratings_list)
            
            if st.form_submit_button("Save Camera") and name and url:
                c.execute("INSERT INTO cameras (name, location, coordinates, url, traffic_vision_link, rating, submitted_by, link_to_id, position) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)", 
                          (name, loc, coords, url, vision_link, rating, st.session_state["username"]))
                conn.commit()
                sync_to_github() 
                st.success("Camera saved and synced!")
                st.rerun()
                
    elif action == "Edit Existing Camera":
        c.execute("SELECT id, name, position, link_to_id FROM cameras")
        all_cams = c.fetchall()
        
        if all_cams:
            # Build helper dictionary for display name mapping
            id_to_name = {row[0]: row[1] for row in all_cams}
            
            cam_options = {}
            for cid, cname, cpos, cparent in all_cams:
                if cpos and cparent in id_to_name:
                    display_label = f"{cname} [Tree: {cpos} of {id_to_name[cparent]}]"
                else:
                    display_label = f"{cname} [Main Camera]"
                cam_options[display_label] = cid
                
            selected_label = st.selectbox("Select Camera to Edit / Delete", list(cam_options.keys()))
            selected_id = cam_options[selected_label]
            
            c.execute("SELECT name, location, coordinates, url, traffic_vision_link, rating, link_to_id, position FROM cameras WHERE id = ?", (selected_id,))
            curr = c.fetchone()
            
            with st.form("edit_form"):
                e_name = st.text_input("Camera Name", value=curr[0])
                e_loc = st.text_input("Location", value=curr[1] or "")
                e_coords = st.text_input("Coordinates", value=curr[2] or "")
                e_url = st.text_input("Stream URL", value=curr[3])
                e_vision_link = st.text_input("Traffic Vision Link", value=curr[4] or "")
                
                try:
                    r_index = ratings_list.index(curr[5])
                except ValueError:
                    r_index = 0
                e_rating = st.selectbox("Rating", ratings_list, index=r_index)
                
                # If it's a tree node, allow changing its relation/position
                is_tree_node = curr[6] is not None
                e_position = curr[7]
                if is_tree_node:
                    pos_options = ["Before (Upstream)", "After (Downstream)"]
                    current_pos_idx = 0 if e_position == "Before" else 1
                    chosen_pos = st.selectbox("Tree Position", pos_options, index=current_pos_idx)
                    e_position = "Before" if "Before" in chosen_pos else "After"
                
                col1, col2 = st.columns(2)
                with col1:
                    update_btn = st.form_submit_button("Update")
                with col2:
                    delete_btn = st.form_submit_button("Delete")
                    
                if update_btn and e_name and e_url:
                    if is_tree_node:
                        c.execute("UPDATE cameras SET name=?, location=?, coordinates=?, url=?, traffic_vision_link=?, rating=?, position=? WHERE id=?", 
                                  (e_name, e_loc, e_coords, e_url, e_vision_link, e_rating, e_position, selected_id))
                    else:
                        c.execute("UPDATE cameras SET name=?, location=?, coordinates=?, url=?, traffic_vision_link=?, rating=? WHERE id=?", 
                                  (e_name, e_loc, e_coords, e_url, e_vision_link, e_rating, selected_id))
                    conn.commit()
                    sync_to_github() 
                    st.success("Updated and synced successfully!")
                    st.rerun()
                elif delete_btn:
                    # Delete the camera and any child nodes linked to it if it's a main camera
                    c.execute("DELETE FROM cameras WHERE id = ? OR link_to_id = ?", (selected_id, selected_id))
                    conn.commit()
                    sync_to_github() 
                    st.warning("Camera (and its linked tree nodes) deleted and synced!")
                    st.rerun()
        else:
            st.info("No cameras available to edit.")

    else: # Link Nearby Cam (Tree)
        c.execute("SELECT id, name FROM cameras WHERE link_to_id IS NULL OR link_to_id = 0")
        cams = c.fetchall()
        if cams:
            cam_dict = {name: cid for cid, name in cams}
            target_name = st.selectbox("Select Main Target Camera", list(cam_dict.keys()))
            target_id = cam_dict[target_name]
            
            relation = st.selectbox("Relationship", ["Before (Upstream)", "After (Downstream)"])
            
            with st.form("tree_form"):
                t_name = st.text_input("Nearby Camera Name")
                t_loc = st.text_input("Location")
                t_coords = st.text_input("Coordinates")
                t_url = st.text_input("Stream URL")
                t_vision = st.text_input("Traffic Vision Link")
                t_rating = st.selectbox("Rating", ratings_list)
                
                if st.form_submit_button("Add to Tree") and t_name and t_url:
                    pos = "Before" if "Before" in relation else "After"
                    c.execute("INSERT INTO cameras (name, location, coordinates, url, traffic_vision_link, rating, submitted_by, link_to_id, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                              (t_name, t_loc, t_coords, t_url, t_vision, t_rating, st.session_state["username"], target_id, pos))
                    conn.commit()
                    sync_to_github()
                    st.success("Nearby tree camera added and synced!")
                    st.rerun()
        else:
            st.info("Add a main camera first before creating a tree.")

# Main Interface: Search and Sorting controls
st.subheader("Database List")

df = pd.read_sql("SELECT id, name as Name, location as Location, coordinates as Coordinates, url as API, traffic_vision_link as [Vision Link], rating as Rating, submitted_by as [Submitted By], url as URL, link_to_id, position FROM cameras", conn)

if not df.empty:
    col_search, col_sort, col_order = st.columns([2, 1, 1])
    with col_search:
        search = st.text_input("Search Name, Location, or Coords")
    with col_sort:
        sort_by = st.selectbox("Sort by", ["Name", "Rating", "Location"])
    with col_order:
        sort_order = st.selectbox("Order", ["Ascending", "Descending"])
        
    if search:
        df = df[df['Name'].str.contains(search, case=False, na=False) | 
                df['Location'].str.contains(search, case=False, na=False) |
                df['Coordinates'].str.contains(search, case=False, na=False)]
                
    is_ascending = True if "Ascending" in sort_order else False
    if sort_by in df.columns:
        df = df.sort_values(by=sort_by, ascending=is_ascending)

    display_df = df.drop(columns=['id', 'URL', 'link_to_id', 'position'])

    def color_rating(val):
        if "Green" in str(val):
            return 'background-color: #d4edda; color: #155724; font-weight: bold;'
        elif "Orange" in str(val):
            return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
        elif "Red" in str(val):
            return 'background-color: #f8d7da; color: #721c24; font-weight: bold;'
        return ''

    styled_df = display_df.style.map(color_rating, subset=['Rating'])
    st.dataframe(styled_df, use_container_width=True)
    
    st.divider()
    st.subheader("Live Feeds & Tree Views")
    
    main_cams = df[df['link_to_id'].isna() | (df['link_to_id'] == 0)]
    
    for _, row in main_cams.iterrows():
        coords_display = f" | Coords: `{row['Coordinates']}`" if row['Coordinates'] else ""
        vision_display = f" | [Traffic Vision]({row['Vision Link']})" if row['Vision Link'] else ""
        submitter_display = f" | Submitted by: {row['Submitted By']}" if row['Submitted By'] else ""
        
        st.markdown(f"### 📍 {row['Name']} — *{row['Location']}*{coords_display}{vision_display}{submitter_display} — Status: **{row['Rating']}**")
        
        video_url = row["URL"]
        main_id = row['id']
        hls_player_html = f"""
        <div>
            <video id="video_{main_id}" controls autoplay muted style="width: 100%; max-height: 400px; background: black; border-radius: 8px;"></video>
            <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
            <script>
                var video = document.getElementById('video_{main_id}');
                var videoSrc = "{video_url}";
                if (Hls.isSupported()) {{
                    var hls = new Hls();
                    hls.loadSource(videoSrc);
                    hls.attachMedia(video);
                }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                    video.src = videoSrc;
                }}
            </script>
        </div>
        """
        components.html(hls_player_html, height=320)
        
        c.execute("SELECT id, name, location, coordinates, url, traffic_vision_link, rating, submitted_by, position FROM cameras WHERE link_to_id = ?", (int(main_id),))
        linked_cams = c.fetchall()
        
        if linked_cams:
            with st.expander(f"🌲 View Nearby Tree ({len(linked_cams)} linked cams)"):
                for l_cam in linked_cams:
                    l_id, l_name, l_loc, l_coords, l_url, l_vision, l_rating, l_sub, l_pos = l_cam
                    pos_label = "⬆️ BEFORE (Upstream)" if l_pos == "Before" else "⬇️ AFTER (Downstream)"
                    l_coords_disp = f" | Coords: `{l_coords}`" if l_coords else ""
                    l_vision_disp = f" | [Traffic Vision]({l_vision})" if l_vision else ""
                    l_sub_disp = f" | Submitted by: {l_sub}" if l_sub else ""
                    
                    st.markdown(f"**{pos_label}: {l_name}** — *{l_loc}*{l_coords_disp}{l_vision_disp}{l_sub_disp} — Status: **{l_rating}**")
                    
                    sub_player_html = f"""
                    <div>
                        <video id="video_sub_{l_id}" controls autoplay muted style="width: 100%; max-height: 300px; background: black; border-radius: 8px;"></video>
                        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
                        <script>
                            var video = document.getElementById('video_sub_{l_id}');
                            var videoSrc = "{l_url}";
                            if (Hls.isSupported()) {{
                                var hls = new Hls();
                                hls.loadSource(videoSrc);
                                hls.attachMedia(video);
                            }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                                video.src = videoSrc;
                            }}
                        </script>
                    </div>
                    """
                    components.html(sub_player_html, height=240)
                    st.divider()
        st.divider()
else:
    st.info("No cameras added yet. Use the sidebar to add one.")