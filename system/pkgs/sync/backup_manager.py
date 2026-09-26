import os
import shutil
import json
from datetime import datetime
import hashlib

class BackupManager:
    # ... (init, _get_project_hash, etc. are unchanged) ...
    def __init__(self, repo_root=None):
        base_dir = repo_root if repo_root else os.path.join(os.path.expanduser("~"), ".sync_repo")
        self.backup_root = os.path.normpath(base_dir)
        self.metadata_dir = os.path.join(self.backup_root, "metadata")
        os.makedirs(self.metadata_dir, exist_ok=True)
    def _get_project_hash(self, source_path):
        return hashlib.md5(os.path.normpath(source_path).encode('utf-8')).hexdigest()
    def _get_project_repo_path(self, source_path):
        return os.path.join(self.backup_root, self._get_project_hash(source_path))
    def _get_metadata_path(self, source_path):
        return os.path.join(self.metadata_dir, f"{self._get_project_hash(source_path)}.json")
    def _read_metadata(self, source_path):
        meta_path = self._get_metadata_path(source_path)
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {"source_path": source_path, "versions": []}
        return {"source_path": source_path, "versions": []}
    def _write_metadata(self, metadata):
        meta_path = self._get_metadata_path(metadata["source_path"])
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
    
    def create_backup(self, source_path, items_to_backup, description):
        if not items_to_backup: return False, "没有选择任何要备份的文件。"
        project_repo_path = self._get_project_repo_path(source_path)
        os.makedirs(project_repo_path, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version_path = os.path.join(project_repo_path, timestamp)
        try:
            os.makedirs(version_path)
            # <<< CHANGE: We now store the original selected items for better metadata.
            file_count = 0
            for item in items_to_backup:
                source_item_path = os.path.join(source_path, item)
                dest_item_path = os.path.join(version_path, item)
                if not os.path.exists(source_item_path): continue
                if os.path.isdir(source_item_path):
                    shutil.copytree(source_item_path, dest_item_path, dirs_exist_ok=True)
                    # Count files inside the copied directory
                    for _, _, files in os.walk(dest_item_path):
                        file_count += len(files)
                else:
                    os.makedirs(os.path.dirname(dest_item_path), exist_ok=True)
                    shutil.copy2(source_item_path, dest_item_path)
                    file_count += 1
            
            if file_count == 0 and not any(os.path.isdir(os.path.join(source_path, i)) for i in items_to_backup):
                 shutil.rmtree(version_path)
                 return False, "没有文件被成功备份（可能源文件已不存在）。"

            metadata = self._read_metadata(source_path)
            metadata['versions'].append({
                "timestamp": timestamp, "description": description,
                "file_count": file_count,
                # Store the original backed up items, which includes directories.
                "backed_up_items": items_to_backup 
            })
            self._write_metadata(metadata)
            return True, f"备份成功创建于 {timestamp}"
        except Exception as e:
            if os.path.exists(version_path): shutil.rmtree(version_path)
            return False, f"备份失败: {str(e)}"
    
    def list_backups(self, source_path):
        metadata = self._read_metadata(source_path)
        return sorted(metadata.get("versions", []), key=lambda x: x['timestamp'], reverse=True)
    def restore_backup(self, source_path, timestamp):
        project_repo_path = self._get_project_repo_path(source_path)
        version_path = os.path.join(project_repo_path, timestamp)
        if not os.path.exists(version_path): return False, "指定的备份版本不存在。"
        try:
            shutil.copytree(version_path, source_path, dirs_exist_ok=True)
            return True, f"版本 {timestamp} 已成功恢复。"
        except Exception as e: return False, f"恢复失败: {str(e)}"
    def restore_selective_items(self, source_path, timestamp, items_to_restore):
        project_repo_path = self._get_project_repo_path(source_path)
        version_path = os.path.join(project_repo_path, timestamp)
        if not os.path.exists(version_path): return False, "指定的备份版本不存在。"
        try:
            for item in items_to_restore:
                backup_item_path = os.path.join(version_path, item)
                original_item_path = os.path.join(source_path, item)
                if not os.path.exists(backup_item_path): continue
                if os.path.isdir(backup_item_path):
                    shutil.copytree(backup_item_path, original_item_path, dirs_exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(original_item_path), exist_ok=True)
                    shutil.copy2(backup_item_path, original_item_path)
            return True, f"选中的 {len(items_to_restore)} 个项目已成功恢复。"
        except Exception as e: return False, f"恢复失败: {e}"
    def delete_backups(self, source_path, timestamps):
        project_repo_path = self._get_project_repo_path(source_path)
        metadata = self._read_metadata(source_path)
        versions_to_keep = [v for v in metadata['versions'] if v['timestamp'] not in timestamps]
        for timestamp in timestamps:
            version_path = os.path.join(project_repo_path, timestamp)
            if os.path.exists(version_path): shutil.rmtree(version_path)
        metadata['versions'] = versions_to_keep
        self._write_metadata(metadata)
        if not versions_to_keep and os.path.exists(project_repo_path):
            if not os.listdir(project_repo_path): os.rmdir(project_repo_path)
        return True, f"成功删除 {len(timestamps)} 个备份。"
    def get_all_tracked_projects(self):
        projects = {}
        for meta_file in os.listdir(self.metadata_dir):
            if meta_file.endswith(".json"):
                try:
                    with open(os.path.join(self.metadata_dir, meta_file), 'r', encoding='utf-8') as f: data = json.load(f)
                    if "source_path" in data and data.get("versions"):
                        projects[data["source_path"]] = len(data["versions"])
                except (json.JSONDecodeError, IOError, KeyError): continue
        return projects

    # <<< NEW: The definitive method to get version contents.
    def get_version_contents(self, source_path, timestamp):
        """
        Gets all files and directories for a version by walking the backup folder.
        This is the most reliable way to reconstruct the tree.
        Returns a set of all relative paths (both files and dirs).
        """
        project_repo_path = self._get_project_repo_path(source_path)
        version_path = os.path.join(project_repo_path, timestamp)

        if not os.path.exists(version_path):
            return None

        all_paths = set()
        for root, dirs, files in os.walk(version_path):
            rel_root = os.path.relpath(root, version_path)
            for name in dirs + files:
                if rel_root == ".":
                    all_paths.add(name)
                else:
                    all_paths.add(os.path.join(rel_root, name).replace('\\', '/'))
        return all_paths