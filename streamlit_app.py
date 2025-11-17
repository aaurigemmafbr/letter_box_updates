# streamlit_app.py
import streamlit as st
import os
import json
import keyring
from github_helpers import get_github_client, list_text_files_in_folder, read_file_contents, safe_replace_between_tags, write_or_update_file, get_json_from_repo

st.set_page_config(page_title="Letterbox: Template Updater", layout="wide")

st.title("Letterbox — wording & signature updates (private repo)")

# ---------------------------
# Token resolution
# ---------------------------
def resolve_token():
    # 1) Streamlit secrets (when deployed on Streamlit Cloud)
    if st.secrets.get("GITHUB_TOKEN"):
        return st.secrets["GITHUB_TOKEN"]
    # 2) Environment variable
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ.get("GITHUB_TOKEN")
    # 3) OS keyring (local dev)
    try:
        tk = keyring.get_password("github", "github_token")
        if tk:
            return tk
    except Exception:
        pass
    return None

token = resolve_token()
if not token:
    st.error("No GitHub token found. Set GITHUB_TOKEN in Streamlit secrets, or as environment var, or in keyring under service 'github' / user 'github_token'.")
    st.stop()

g = get_github_client(token)

# ---------------------------
# Private repo configuration
# ---------------------------
st.sidebar.header("Private repo settings")
repo_owner = st.sidebar.text_input("Repo owner (user or org)", value="", help="owner of the private repo")
repo_name = st.sidebar.text_input("Repo name", value="", help="private repo name (e.g. my-org/letter-templates). Enter name only; owner field above required.")

branch = st.sidebar.text_input("Branch to update", value="main")

if not repo_owner or not repo_name:
    st.info("Enter private repo owner and name in the sidebar to proceed.")
    st.stop()

repo_fullname = f"{repo_owner}/{repo_name}"
try:
    repo = g.get_repo(repo_fullname)
except Exception as e:
    st.error(f"Unable to open repo {repo_fullname}: {e}")
    st.stop()

# ---------------------------
# UI: choose operation
# ---------------------------
operation = st.radio("Choose update type:", ("Wording updates", "Signature updates"))

# Common helper: preview list of base_templates files
st.sidebar.markdown("### Repo folders (read-only preview)")
with st.sidebar.expander("Preview `base_templates` and `updated_letters` file counts"):
    base_files = list_text_files_in_folder(repo, "base_templates")
    updated_files = list_text_files_in_folder(repo, "updated_letters")
    st.write(f"Found {len(base_files)} files in `base_templates`")
    st.write(f"Found {len(updated_files)} files in `updated_letters`")

# ---------------------------
# WORDING UPDATES flow
# ---------------------------
if operation == "Wording updates":
    st.header("Wording updates — paste text to inject into base templates")
    paste_block = st.text_area("Paste the block of text to insert into templates:", height=300)
    confirm_writing = st.checkbox("I confirm: inject this text into every .txt in base_templates and commit to updated_letters (overwrite same filenames).")
    if st.button("Run wording update"):
        if not paste_block.strip():
            st.error("Please paste a non-empty block of text.")
        elif not confirm_writing:
            st.warning("Please check the confirmation checkbox to proceed.")
        else:
            status = st.empty()
            progress = st.progress(0)
            total = max(1, len(base_files))
            i = 0
            results = []
            for f in base_files:
                i += 1
                progress.progress(int(i/total*100))
                try:
                    original_text, sha = read_file_contents(repo, f.path)
                    new_text = safe_replace_between_tags(original_text,
                                                         "<!-- start here -->",
                                                         "<!-- end here -->",
                                                         paste_block)
                    target_path = f"updated_letters/{f.name}"
                    commit_message = f"Wording update: injected block into {f.name}"
                    res = write_or_update_file(repo, target_path, new_text, commit_message, branch=branch)
                    results.append((f.name, "ok", res))
                except Exception as e:
                    results.append((f.name, "error", str(e)))
            progress.progress(100)
            st.success("Wording updates finished")
            st.write("Results:")
            st.dataframe([{"file": r[0], "status": r[1], "detail": r[2]} for r in results])

# ---------------------------
# SIGNATURE UPDATES flow
# ---------------------------
else:
    st.header("Signature updates — select Denver or WSlope and choose signers")
    # Load template JSON from private repo
    config_path = "config/signatures.json"
    try:
        config_json, _ = get_json_from_repo(repo, config_path)
    except Exception as e:
        st.error(f"Could not read {config_path} from repo: {e}")
        st.stop()

    location = st.selectbox("Location to update signatures for:", ("Denver", "WSlope"))
    loc_key = location.lower()  # "denver" or "wslope"

    # Build dropdown options from JSON for the chosen location
    preconfigured = config_json.get(loc_key, [])
    # preconfigured is expected to be list of dicts with keys: name, title, min_gift, max_gift (max optional or null)
    options = ["-- choose preconfigured signee --", *[
        f'{p["name"]} — {p.get("title","")} — ${p["min_gift"]:,}' for p in preconfigured
    ]]
    options.append("Other (enter custom)")
    selected = st.selectbox("Choose a preconfigured signee or 'Other':", options)

    custom_signees = []
    selected_slot = None

    if selected == "Other (enter custom)":
        st.info("Enter custom signee info. You can create up to 4 custom signees.")
        # Allow adding up to 4 custom signees
        max_custom = 4
        num_custom = st.number_input("How many custom signees to add (1-4)", min_value=1, max_value=max_custom, value=1)
        for idx in range(int(num_custom)):
            st.markdown(f"**Custom signee {idx+1}**")
            cname = st.text_input(f"Name (custom {idx+1})", key=f"name_{idx}")
            ctitle = st.text_input(f"Title (custom {idx+1})", key=f"title_{idx}")
            min_g = st.number_input(f"Min gift for this signee (inclusive) (custom {idx+1})", min_value=0.0, step=0.01, key=f"mingift_{idx}")
            # optionally allow upper bound
            max_g = st.number_input(f"Max gift for this signee (inclusive) or 0 for none (custom {idx+1})", min_value=0.0, step=0.01, key=f"maxgift_{idx}")
            custom_signees.append({
                "name": cname.strip(),
                "title": ctitle.strip(),
                "min_gift": float(min_g),
                "max_gift": float(max_g) if float(max_g) > 0 else None
            })
    else:
        # map selection back to the chosen preconfigured item
        if selected != "-- choose preconfigured signee --":
            idx = options.index(selected) - 1
            chosen = preconfigured[idx]
            custom_signees.append({
                "name": chosen["name"],
                "title": chosen.get("title", ""),
                "min_gift": float(chosen.get("min_gift", 0)),
                "max_gift": chosen.get("max_gift", None)
            })

    # Optionally let user add more preconfigured or custom to build an ordered set up to 4 total
    st.markdown("### Build tiers (ordered highest-to-lowest)")
    st.info("You must arrange tiers from highest min_gift down to lowest; the logic will produce nested {{#if}} ... {{else}} ... {{/if}} statements accordingly.")
    # Let user build final tiers list
    tiers = []
    if custom_signees:
        for s in custom_signees:
            tiers.append(s)

    # show a place to reorder or add additional preconfigured signees
    st.write("Current tiers (you should order them highest-to-lowest min_gift):")
    for idx, t in enumerate(tiers):
        st.write(f"{idx+1}. {t['name']} — {t.get('title','')} — min ${t['min_gift']:,}  max {'—' if not t.get('max_gift') else '$'+str(t['max_gift'])}")

    # allow user to add another preconfigured
    add_pre_idx = st.selectbox("Add another preconfigured signer (optional):", ["None", *[p["name"] for p in preconfigured]])
    if st.button("Add preconfigured"):
        if add_pre_idx != "None":
            chosen = next((p for p in preconfigured if p["name"]==add_pre_idx), None)
            if chosen:
                tiers.append({"name": chosen["name"], "title": chosen.get("title",""), "min_gift": float(chosen.get("min_gift",0)), "max_gift": chosen.get("max_gift", None)})
                st.experimental_rerun()

    # final confirmation and run
    confirm_sig = st.checkbox("I confirm: generate signature snippet and replace corresponding signature blocks in all '*_live' files in 'updated_letters' folder.", key="confirm_sig")

    if st.button("Run signature update"):
        if not tiers:
            st.error("No signees configured. Add preconfigured or custom signees.")
        elif not confirm_sig:
            st.warning("Please check confirmation checkbox to proceed.")
        else:
            # sort tiers descending by min_gift
            tiers_sorted = sorted(tiers, key=lambda x: x["min_gift"], reverse=True)
            st.write("Final tiers (descending):")
            for t in tiers_sorted:
                st.write(f"- {t['name']} — min ${t['min_gift']:,}  max {t.get('max_gift') or 'no max'}")

            # Build handlebars snippet
            def build_handlebars(tiers_list):
                """
                Build nested if/else handlebars structure exactly like:
                {{#if (compare Gift.amount.value ">" 9999.99)}}
                <p>Name<br>Title</p>
                {{else}} {{#if (compare Gift.amount.value ">" 499.99)}}
                <p>Name<br>Title</p>
                {{/if}}{{/if}}
                """
                out_lines = []
                n = len(tiers_list)
                if n == 0:
                    return ""
                # For each but the last, add an if; last is else content
                for i, tier in enumerate(tiers_list):
                    name = tier["name"]
                    title = tier.get("title","")
                    min_g = float(tier["min_gift"])
                    # We must write a comparison ">" (min_g - 0.01) to represent >= min_g
                    compare_value = (min_g - 0.01)
                    compare_value_str = f"{compare_value:0.2f}"
                    if i < n - 1:
                        out_lines.append(f'{{{{#if (compare Gift.amount.value ">" {compare_value_str})}}}}')
                        out_lines.append("<p>")
                        out_lines.append(name)
                        out_lines.append("<br>")
                        out_lines.append(title)
                        out_lines.append("</p>")
                        out_lines.append("{{{{else}}}}")
                    else:
                        # last tier - provide as else content (no further if)
                        out_lines.append("<p>")
                        out_lines.append(name)
                        out_lines.append("<br>")
                        out_lines.append(title)
                        out_lines.append("</p>")
                        # close previous opened {{#if}} blocks
                        # After building full else content, we'll append close tags equal to number of opens (n-1)
                # now append closing tags: one {{/if}} for each nested if
                for i in range(n - 1):
                    out_lines.append("{{{{/if}}}}")
                return "\n".join(out_lines)

            snippet = build_handlebars(tiers_sorted)
            st.code(snippet, language="")

            # Now find live files in updated_letters that end with _live (case-insensitive)
            live_files = [f for f in list_text_files_in_folder(repo, "updated_letters") if f.name.lower().endswith("_live.txt")]
            st.write(f"Found {len(live_files)} _live files in updated_letters to update.")
            results = []
            for f in live_files:
                try:
                    original_text, sha = read_file_contents(repo, f.path)
                    if loc_key == "denver":
                        start_tag = "<!-- denver sig start -->"
                        end_tag = "<!-- denver sig end -->"
                    else:
                        start_tag = "<!-- wslope sig start -->"
                        end_tag = "<!-- wslope sig end -->"
                    new_text = safe_replace_between_tags(original_text, start_tag, end_tag, snippet)
                    commit_message = f"Signature update ({location}) for {f.name}"
                    res = write_or_update_file(repo, f.path, new_text, commit_message, branch=branch)
                    results.append((f.name, "ok", res))
                except Exception as e:
                    results.append((f.name, "error", str(e)))
            st.success("Signature updates finished")
            st.dataframe([{"file": r[0], "status": r[1], "detail": r[2]} for r in results])
