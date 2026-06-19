#!/usr/bin/env python3
"""
Get git diff for staged and unstaged changes with context awareness.
Provides structured output for commit message generation with previous commit context.
"""
import subprocess
import sys
import json


def run_git_command(cmd):
    """Run a git command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return None


def get_last_commit_info():
    """Get information about the last commit."""
    # Get last commit message
    last_message = run_git_command("git log -1 --pretty=%B")
    
    # Get last commit hash
    last_hash = run_git_command("git log -1 --pretty=%H")
    
    # Get last commit diff stats
    last_diff_stats = run_git_command("git diff HEAD~1..HEAD --stat")
    
    # Get files changed in last commit
    last_files = run_git_command("git diff HEAD~1..HEAD --name-status")
    
    # Get last commit date
    last_date = run_git_command("git log -1 --pretty=%ar")
    
    return {
        "message": last_message if last_message else "No previous commit",
        "hash": last_hash if last_hash else "",
        "stats": last_diff_stats if last_diff_stats else "",
        "files": last_files if last_files else "",
        "date": last_date if last_date else ""
    }


def get_diff_stats():
    """Get statistics about the changes."""
    # Get staged changes
    staged_diff = run_git_command("git diff --cached --stat")
    
    # Get unstaged changes
    unstaged_diff = run_git_command("git diff --stat")
    
    # Get full diff for context
    staged_full = run_git_command("git diff --cached")
    unstaged_full = run_git_command("git diff")
    
    return {
        "staged": {
            "stat": staged_diff if staged_diff else "No staged changes",
            "diff": staged_full if staged_full else ""
        },
        "unstaged": {
            "stat": unstaged_diff if unstaged_diff else "No unstaged changes",
            "diff": unstaged_full if unstaged_full else ""
        }
    }


def get_changed_files():
    """Get list of changed files with their status."""
    # Staged files
    staged = run_git_command("git diff --cached --name-status")
    
    # Unstaged files
    unstaged = run_git_command("git diff --name-status")
    
    return {
        "staged": staged if staged else "",
        "unstaged": unstaged if unstaged else ""
    }


def analyze_relationship_to_last_commit(last_commit_info, current_changes):
    """Analyze if current changes are related to last commit."""
    if not last_commit_info["message"] or last_commit_info["message"] == "No previous commit":
        return None
    
    # Get files from last commit
    last_files = set()
    if last_commit_info["files"]:
        for line in last_commit_info["files"].split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 2:
                    last_files.add(parts[1])
    
    # Get current staged files
    current_files = set()
    if current_changes["staged"]:
        for line in current_changes["staged"].split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 2:
                    current_files.add(parts[1])
    
    # Calculate file overlap
    overlap = last_files.intersection(current_files)
    overlap_ratio = len(overlap) / len(last_files) if last_files else 0
    
    return {
        "overlap_files": list(overlap),
        "overlap_ratio": overlap_ratio,
        "last_files": list(last_files),
        "current_files": list(current_files)
    }


def main():
    """Main function to output git diff information with context."""
    # Check if we're in a git repository
    is_git_repo = run_git_command("git rev-parse --git-dir")
    if is_git_repo is None:
        print("Error: Not a git repository", file=sys.stderr)
        sys.exit(1)
    
    # Get current diff information
    diff_stats = get_diff_stats()
    changed_files = get_changed_files()
    
    # Get last commit information
    last_commit = get_last_commit_info()
    
    # Analyze relationship
    relationship = analyze_relationship_to_last_commit(last_commit, changed_files)
    
    # Output in a readable format
    print("=== COMMIT CONTEXT ANALYSIS ===\n")
    
    print("LAST COMMIT INFORMATION:")
    print(f"Hash: {last_commit['hash'][:8] if last_commit['hash'] else 'N/A'}")
    print(f"Date: {last_commit['date']}")
    print(f"Message:\n{last_commit['message']}")
    print()
    
    if last_commit["stats"]:
        print("Last Commit Changes:")
        print(last_commit["stats"])
        print()
    
    print("\n=== CURRENT CHANGES SUMMARY ===\n")
    
    print("STAGED CHANGES:")
    print(diff_stats["staged"]["stat"])
    if changed_files["staged"]:
        print("\nFiles:")
        print(changed_files["staged"])
    print()
    
    print("\nUNSTAGED CHANGES:")
    print(diff_stats["unstaged"]["stat"])
    if changed_files["unstaged"]:
        print("\nFiles:")
        print(changed_files["unstaged"])
    print()
    
    # Output relationship analysis
    if relationship and relationship["overlap_ratio"] > 0:
        print("\n=== RELATIONSHIP TO LAST COMMIT ===\n")
        print(f"File Overlap: {len(relationship['overlap_files'])} files")
        print(f"Overlap Ratio: {relationship['overlap_ratio']:.1%}")
        if relationship["overlap_files"]:
            print(f"Common Files: {', '.join(relationship['overlap_files'])}")
        print()
        print("⚠️  NOTICE: Current changes overlap with last commit.")
        print("Consider if this is:")
        print("  • A continuation (延续) of the same feature")
        print("  • A fix (修复) for the previous commit")
        print("  • A rollback (回滚) of previous changes")
        print()
    
    # Output full diff for staged changes (most relevant for commits)
    if diff_stats["staged"]["diff"]:
        print("\n=== STAGED DIFF DETAILS ===")
        print(diff_stats["staged"]["diff"])


if __name__ == "__main__":
    main()
