---
name: git-commit-generator
description: Generate context-aware, well-formatted git commit messages in Chinese based on git diff analysis. Analyzes relationship to previous commit (continuation/fix/rollback) to maintain semantic continuity across multiple related commits. Use when the user requests to create a commit message, generate commit content, review changes for commit, or prepare a commit description. Does NOT actually commit changes - only generates the commit message text.
---

# Git Commit Generator

## Overview

Analyze git changes and generate **context-aware** structured commit messages in **Chinese (中文)** following conventional commit format. This skill examines both staged/unstaged changes AND the previous commit to determine if the current commit is a continuation (延续), fix (修复), or rollback (回滚) of previous work.

**Key Innovation: Evolutionary Commit Generation (演进型生成)**

Instead of treating each commit in isolation, this skill analyzes:
- What was committed last time (上次提交内容)
- What is being committed now (当前提交内容)  
- File overlap and semantic relationship (文件重叠与语义关系)

This enables intelligent handling of **multiple small, related commits** by recognizing patterns like:
- Feature continuation across multiple commits
- Quick fixes to recently introduced bugs
- Incremental improvements to the same module
- Rollbacks of problematic changes

The result: commit messages that tell a coherent story rather than isolated snapshots.

## Workflow

### Step 1: Retrieve Git Changes

Run the `get_diff.py` script to retrieve git change information:

```bash
python3 scripts/get_diff.py
```

This script provides:
- Summary statistics of changed files
- File status (Added, Modified, Deleted)
- Full diff output for staged changes

### Step 2: Analyze Changes with Context

**Context-Aware Analysis:**

The script provides three key pieces of information:
1. **Last Commit Information**: Previous commit message, files changed, and timing
2. **Current Changes**: Files being committed now
3. **Relationship Analysis**: File overlap and potential relationship type

Review the output to understand:
- What files were changed in the LAST commit
- What files are being changed NOW
- Whether there is file overlap (suggesting related changes)
- The scope and purpose of current changes

**Critical Decision Point:**

If there is significant file overlap (>30%) with the last commit, determine the relationship:

**延续 (Continuation):**
- Adding more functionality to the same feature
- Completing work started in last commit
- Expanding on previous implementation
- Format: `feat: 继续实现XXX功能` or `feat: 完善XXX功能`
- Example: 
  - Last: `feat: 添加用户登录功能`
  - Now: `feat: 继续实现用户登录功能 - 添加记住密码选项`

**修复 (Fix):**
- Fixing bugs introduced in last commit
- Correcting mistakes from previous implementation
- Addressing issues found after last commit
- Format: `fix: 修复XXX问题` (reference the original feature if relevant)
- Example:
  - Last: `feat: 添加用户登录功能`
  - Now: `fix: 修复登录时的空指针异常`

**回滚 (Rollback/Revert):**
- Undoing changes from last commit
- Removing problematic features
- Reverting to previous state
- Format: `revert: 回滚XXX` or `chore: 移除XXX`
- Example:
  - Last: `feat: 添加实验性缓存功能`
  - Now: `revert: 回滚实验性缓存功能（性能问题）`

**独立 (Independent):**
- No significant overlap or unrelated changes
- New feature or different area of codebase
- Format: Standard commit types
- Example: Last commit was about login, now working on payment module

### Step 3: Generate Context-Aware Commit Message

**CRITICAL: All commit messages must be in Chinese (中文).**

**Decision Tree for Commit Message Generation:**

#### 1. Check Relationship to Last Commit

If the script shows **file overlap >30%**, analyze the relationship type:

**For 延续 (Continuation):**
```
feat: 继续实现<功能名称>
- <本次添加的具体内容1>
- <本次添加的具体内容2>
- 承接上次提交: <简要说明上次做了什么>
```

Example:
```
feat: 继续实现用户认证系统
- 添加双因素认证支持
- 实现OAuth第三方登录
- 承接上次提交: 基础的用户名密码登录
```

**For 修复 (Fix):**
```
fix: 修复<具体问题>
- <修复的具体内容1>
- <修复的具体内容2>
- 修复上次提交引入的问题: <问题描述>
```

Example:
```
fix: 修复登录时的会话管理问题
- 添加会话过期检查
- 修复token刷新逻辑
- 修复上次提交引入的问题: 并发登录时会话冲突
```

**For 回滚 (Rollback):**
```
revert: 回滚<功能/更改>
- 移除<具体内容1>
- 移除<具体内容2>
- 回滚原因: <为什么要回滚>
```

Example:
```
revert: 回滚实验性缓存策略
- 移除Redis缓存层
- 恢复直接数据库查询
- 回滚原因: 缓存失效导致数据不一致
```

#### 2. If No Significant Overlap (Independent Commit)

Use standard commit format:

```
<type>: <简短总结>
- <变更详情1>
- <变更详情2>
- <变更详情3>
```

**Commit Types:**
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档修改
- `style`: 代码格式修改（不影响功能）
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建、依赖等维护任务
- `perf`: 性能优化

**Guidelines:**
- **All descriptions and bullet points MUST be in Chinese (中文)**
- Keep the summary line concise (50-72 characters ideally)
- Use imperative mood in Chinese ("添加功能" not "已添加功能")
- Bullet points should describe specific changes
- Focus on WHAT changed and WHY, not HOW
- Each bullet point should be actionable and clear
- **When related to last commit, explicitly mention the relationship**

### Step 4: Present the Commit Message

Display the generated commit message to the user. Make it clear this is a SUGGESTED message that they can:
- Use as-is with `git commit -m "..."`
- Modify before committing
- Use as a starting point for a more detailed commit message

**Important:** This skill does NOT execute the commit. It only generates the message text.

## Example Usage

### Example 1: Independent Commit (No Context)

**User Request:** "Generate a commit message for my changes"

**Claude Response:**
1. Run `python3 scripts/get_diff.py`
2. Analyze the output
3. Notice: No previous commit or no file overlap
4. Generate formatted commit message **in Chinese**:

```
feat: 添加用户认证系统
- 实现JWT token生成和验证
- 添加登录和注册端点
- 创建用户模型并支持密码哈希
- 添加保护路由的认证中间件
```

### Example 2: Continuation Commit

**Script Output Shows:**
```
LAST COMMIT INFORMATION:
Message: feat: 添加用户认证系统

RELATIONSHIP TO LAST COMMIT:
File Overlap: 3 files
Overlap Ratio: 75%
Common Files: auth.py, user.py, routes.py
```

**Claude Response:**
```
feat: 继续实现用户认证系统
- 添加双因素认证支持
- 实现OAuth第三方登录（Google, GitHub）
- 添加用户权限管理模块
- 承接上次提交: 基础的JWT认证已完成
```

### Example 3: Fix Commit

**Script Output Shows:**
```
LAST COMMIT INFORMATION:
Message: feat: 添加支付处理模块

RELATIONSHIP TO LAST COMMIT:
File Overlap: 2 files
Overlap Ratio: 100%
Common Files: payment.py, transaction.py
```

**Claude Response:**
```
fix: 修复支付处理中的金额计算错误
- 修正小数点精度问题
- 添加金额验证逻辑
- 更新相关单元测试
- 修复上次提交引入的问题: 高并发时金额计算不准确
```

### Example 4: Rollback Commit

**Script Output Shows:**
```
LAST COMMIT INFORMATION:
Message: feat: 添加实验性缓存层

RELATIONSHIP TO LAST COMMIT:
File Overlap: 4 files
Overlap Ratio: 80%
```

**Claude Response:**
```
revert: 回滚实验性Redis缓存层
- 移除Redis缓存相关代码
- 恢复直接数据库查询
- 更新配置文件
- 回滚原因: 缓存失效策略导致数据不一致，影响生产环境
```

### Example 5: Small Sequential Commits

**Scenario:** You make multiple small commits on the same files

**First Commit:**
```
feat: 添加用户导出功能
- 实现基础的CSV导出
```

**Second Commit (with context):**
```
feat: 完善用户导出功能
- 添加Excel导出支持
- 添加导出进度显示
- 承接上次提交: CSV导出已实现
```

**Third Commit (fixing issue):**
```
fix: 修复导出大数据集时的内存溢出
- 改用流式处理
- 添加分批处理逻辑
- 修复上次提交引入的问题: 大量数据导出时内存不足
```

## Resources

### scripts/get_diff.py

Enhanced Python script that retrieves and formats git diff information with context awareness. 

**Outputs:**
- **Last Commit Context**: Previous commit message, hash, date, and changed files
- **Current Changes**: Staged vs unstaged changes with file statistics
- **Relationship Analysis**: Calculates file overlap ratio between current and last commit
- **Full Diff Content**: Complete diff for detailed analysis

**Context Analysis:**
- Identifies which files were changed in both commits
- Calculates overlap ratio to suggest relationship type
- Provides hints for whether this is a continuation, fix, or rollback
- Shows timing information to understand commit cadence

**Key Features:**
- `git diff --cached` for staged changes
- `git diff HEAD~1..HEAD --stat` for last commit comparison
- `git log -1` for last commit metadata
- Automatic relationship type suggestions when overlap >30%

This enhanced script enables "evolutionary commit generation" (演进型生成) rather than just "state-based generation" (状态型生成), helping maintain semantic continuity across multiple related commits.
