# github_helpers.py
from github import Github, InputGitTreeElement
import os
import keyring
import base64
import re

def get_github_client(token: str = None):
    """
    Return a PyGithub Github client. Token resolution performed outside
    (prefer st.secrets, env var, keyring).
    """
    if not token:
        raise ValueError("GitHub token required")
    return Github(token)

def list_text_files_in_folder(repo, folder_path):
    """
    Return list of ContentFile objects for files in a folder path.
    """
    try:
        contents = repo.get_contents(folder_path)
    except Exception as e:
        # folder missing -> empty list
        return []
    files = [c for c in contents if c.type == "file" and c.name.lower().endswith(".txt")]
    return files

def read_file_contents(repo, path):
    """
    Return decoded string contents for a file at path.
    """
    contents = repo.get_contents(path)
    raw = contents.decoded_content.decode("utf-8")
    return raw, contents.sha

def safe_replace_between_tags(original_text, start_tag, end_tag, new_inner_text):
    """
    Replace everything between start_tag and end_tag (inclusive of tags is not replaced,
    only inner content) with new_inner_text. Returns new text.
    If tags aren't present, raises ValueError.
    """
    pattern = re.compile(
        re.escape(start_tag) + r"(.*?)" + re.escape(end_tag),
        flags=re.DOTALL | re.IGNORECASE
    )
    if not pattern.search(original_text):
        raise ValueError(f"Tags not found: {start_tag} ... {end_tag}")
    replacement = start_tag + "\n" + new_inner_text + "\n" + end_tag
    new_text = pattern.sub(replacement, original_text)
    return new_text

def write_or_update_file(repo, path, new_text, commit_message, branch="main"):
    """
    Create or update file at path in repo. Uses repo.get_contents+update_file or create_file.
    """
    try:
        contents = repo.get_contents(path, ref=branch)
        repo.update_file(contents.path, commit_message, new_text, contents.sha, branch=branch)
        return {"action": "updated", "path": path}
    except Exception as e:
        # create if not exists
        try:
            repo.create_file(path, commit_message, new_text, branch=branch)
            return {"action": "created", "path": path}
        except Exception as e2:
            raise

def get_json_from_repo(repo, path):
    """
    Read a JSON file from repo and return parsed JSON (calls read_file_contents).
    """
    import json
    text, sha = read_file_contents(repo, path)
    return json.loads(text), sha
