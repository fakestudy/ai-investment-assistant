# Skill authoring best practices

> 了解如何编写 Claude 能成功发现并有效使用的 Skills。

好的 Skills 应当简洁、结构清晰，并经过真实使用测试。本指南提供实用的编写决策，帮助你写出 Claude 能发现并有效使用的 Skills。

关于 Skills 如何工作的概念背景，请参见 [Skills overview](/en/docs/agents-and-tools/agent-skills/overview)。

## Core principles

### Concise is key

[context window](https://platform.claude.com/docs/en/build-with-claude/context-windows) 是一种公共资源。你的 Skill 需要与 Claude 还必须知道的其他内容共享上下文窗口，包括：

* system prompt
* conversation history
* 其他 Skills 的 metadata
* 你的实际请求

并不是 Skill 中的每个 token 都会立刻产生成本。启动时，所有 Skills 里预加载的只有 metadata（name 和 description）。Claude 只会在 Skill 变得相关时读取 `SKILL.md`，并且只在需要时读取附加文件。不过，`SKILL.md` 保持简洁仍然很重要：一旦 Claude 加载了它，其中每个 token 都会与 conversation history 和其他上下文竞争。

**Default assumption**：Claude 本身已经很聪明

只添加 Claude 本来不知道的上下文。对每一段信息都提出质疑：

* “Claude 真的需要这段解释吗？”
* “我能否假设 Claude 已经知道这个？”
* “这一段值得它消耗的 token 成本吗？”

**Good example: Concise**（约 50 tokens）：

````markdown  theme={null}
## Extract PDF text

Use pdfplumber for text extraction:

```python
import pdfplumber

with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```
````

**Bad example: Too verbose**（约 150 tokens）：

```markdown  theme={null}
## Extract PDF text

PDF (Portable Document Format) files are a common file format that contains
text, images, and other content. To extract text from a PDF, you'll need to
use a library. There are many libraries available for PDF processing, but we
recommend pdfplumber because it's easy to use and handles most cases well.
First, you'll need to install it using pip. Then you can use the code below...
```

简洁版假定 Claude 知道 PDF 是什么，也知道 library 的基本用法。

### Set appropriate degrees of freedom

让具体程度与任务的脆弱性和可变性相匹配。

**High freedom**（文本型说明）：

适用于：

* 多种做法都可行
* 决策依赖上下文
* 主要依靠启发式来指导方法

Example:

```markdown  theme={null}
## Code review process

1. Analyze the code structure and organization
2. Check for potential bugs or edge cases
3. Suggest improvements for readability and maintainability
4. Verify adherence to project conventions
```

**Medium freedom**（带参数的 pseudocode 或脚本）：

适用于：

* 存在首选模式
* 允许一定变化
* 行为受配置影响

Example:

````markdown  theme={null}
## Generate report

Use this template and customize as needed:

```python
def generate_report(data, format="markdown", include_charts=True):
    # Process data
    # Generate output in specified format
    # Optionally include visualizations
```
````

**Low freedom**（具体脚本，参数很少或没有参数）：

适用于：

* 操作脆弱且容易出错
* 一致性至关重要
* 必须遵循特定顺序

Example:

````markdown  theme={null}
## Database migration

Run exactly this script:

```bash
python scripts/migrate.py --verify --backup
```

Do not modify the command or add additional flags.
````

**Analogy**：把 Claude 想象成一个在路径上探索的机器人：

* **两边都是悬崖的窄桥**：只有一条安全路径。你需要给出具体护栏和精确指令（low freedom）。例如：必须按精确顺序执行的 database migration。
* **没有危险的开阔地**：很多路径都能成功。给出总体方向，然后信任 Claude 自己找到最优路线（high freedom）。例如：code review，最佳处理方式依赖上下文。

### Test with all models you plan to use

Skills 是对模型能力的补充，因此效果取决于底层模型。请用你打算使用的所有模型来测试 Skill。

**Testing considerations by model**：

* **Claude Haiku**（快速、经济）：Skill 给出的指导是否足够？
* **Claude Sonnet**（平衡）：Skill 是否清晰且高效？
* **Claude Opus**（强推理）：Skill 是否避免了过度解释？

对 Opus 完美可用的东西，可能对 Haiku 来说仍需要更多细节。如果你计划跨多个模型使用 Skill，就应尽量写出对所有模型都适用的说明。

## Skill structure

<Note>
  **YAML Frontmatter**：`SKILL.md` 的 frontmatter 需要两个字段：

  * `name` - Skill 的可读名称（最多 64 个字符）
  * `description` - 一行描述 Skill 做什么以及何时使用（最多 1024 个字符）

  完整的 Skill 结构细节见 [Skills overview](/en/docs/agents-and-tools/agent-skills/overview#skill-structure)。
</Note>

### Naming conventions

使用一致的命名模式，让 Skills 更容易被引用和讨论。我们建议 Skill 名称使用 **gerund form**（动词 + -ing），因为它能清晰描述 Skill 所提供的活动或能力。

**Good naming examples (gerund form)**：

* "Processing PDFs"
* "Analyzing spreadsheets"
* "Managing databases"
* "Testing code"
* "Writing documentation"

**Acceptable alternatives**：

* 名词短语："PDF Processing"、"Spreadsheet Analysis"
* 动作导向："Process PDFs"、"Analyze Spreadsheets"

**Avoid**：

* 模糊名称："Helper"、"Utils"、"Tools"
* 过于泛化："Documents"、"Data"、"Files"
* 在你的 skill 集合中使用不一致的命名模式

一致命名会让以下事情更容易：

* 在文档和对话中引用 Skills
* 一眼看懂 Skill 是做什么的
* 在多个 Skills 中组织和搜索
* 维护专业且统一的 skill library

### Writing effective descriptions

`description` 字段负责 Skill discovery，应该同时包含 Skill 做什么，以及何时使用。

<Warning>
  **始终使用第三人称。** `description` 会被注入 system prompt，不一致的视角会导致发现问题。

  * **Good:** "Processes Excel files and generates reports"
  * **Avoid:** "I can help you process Excel files"
  * **Avoid:** "You can use this to process Excel files"
</Warning>

**要具体，并包含关键术语。** 同时写出 Skill 做什么，以及触发它的具体场景 / 上下文。

每个 Skill 只有一个 `description` 字段。这个描述对 skill 选择至关重要：Claude 可能要从 100+ 个可用 Skills 中选择合适的一个。你的 description 必须提供足够细节，让 Claude 知道何时该选这个 Skill；而 `SKILL.md` 的其他部分则提供实现细节。

有效示例：

**PDF Processing skill:**

```yaml  theme={null}
description: Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.
```

**Excel Analysis skill:**

```yaml  theme={null}
description: Analyze Excel spreadsheets, create pivot tables, generate charts. Use when analyzing Excel files, spreadsheets, tabular data, or .xlsx files.
```

**Git Commit Helper skill:**

```yaml  theme={null}
description: Generate descriptive commit messages by analyzing git diffs. Use when the user asks for help writing commit messages or reviewing staged changes.
```

避免如下模糊描述：

```yaml  theme={null}
description: Helps with documents
```

```yaml  theme={null}
description: Processes data
```

```yaml  theme={null}
description: Does stuff with files
```

### Progressive disclosure patterns

`SKILL.md` 应作为概览，按需引导 Claude 访问更详细的资料，就像入门指南中的目录。关于 progressive disclosure 如何工作的解释，见总览里的 [How Skills work](/en/docs/agents-and-tools/agent-skills/overview#how-skills-work)。

**Practical guidance:**

* 为了获得最佳性能，尽量把 `SKILL.md` 正文控制在 500 行以内
* 接近这个限制时，把内容拆分到单独文件
* 使用下面的模式来组织说明、代码和资源

#### Visual overview: From simple to complex

一个基础 Skill 一开始只需要一个包含 metadata 和说明的 `SKILL.md` 文件：

<img src="https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-simple-file.png?fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=87782ff239b297d9a9e8e1b72ed72db9" alt="Simple SKILL.md file showing YAML frontmatter and markdown body" data-og-width="2048" width="2048" data-og-height="1153" height="1153" data-path="images/agent-skills-simple-file.png" data-optimize="true" data-opv="3" srcset="https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-simple-file.png?w=280&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=c61cc33b6f5855809907f7fda94cd80e 280w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-simple-file.png?w=560&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=90d2c0c1c76b36e8d485f49e0810dbfd 560w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-simple-file.png?w=840&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=ad17d231ac7b0bea7e5b4d58fb4aeabb 840w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-simple-file.png?w=1100&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=f5d0a7a3c668435bb0aee9a3a8f8c329 1100w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-simple-file.png?w=1650&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=0e927c1af9de5799cfe557d12249f6e6 1650w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-simple-file.png?w=2500&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=46bbb1a51dd4c8202a470ac8c80a893d 2500w" />

随着 Skill 增长，你可以打包只有在需要时才加载的附加内容：

<img src="https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-bundling-content.png?fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=a5e0aa41e3d53985a7e3e43668a33ea3" alt="Bundling additional reference files like reference.md and forms.md." data-og-width="2048" width="2048" data-og-height="1327" height="1153" data-path="images/agent-skills-bundling-content.png" data-optimize="true" data-opv="3" srcset="https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-bundling-content.png?w=280&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=f8a0e73783e99b4a643d79eac86b70a2 280w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-bundling-content.png?w=560&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=dc510a2a9d3f14359416b706f067904a 560w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-bundling-content.png?w=840&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=82cd6286c966303f7dd914c28170e385 840w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-bundling-content.png?w=1100&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=56f3be36c77e4fe4b523df209a6824c6 1100w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-bundling-content.png?w=1650&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=d22b5161b2075656417d56f41a74f3dd 1650w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-bundling-content.png?w=2500&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=3dd4bdd6850ffcc96c6c45fcb0acd6eb 2500w" />

完整的 Skill 目录结构可能像这样：

```
pdf/
├── SKILL.md              # Main instructions (loaded when triggered)
├── FORMS.md              # Form-filling guide (loaded as needed)
├── reference.md          # API reference (loaded as needed)
├── examples.md           # Usage examples (loaded as needed)
└── scripts/
    ├── analyze_form.py   # Utility script (executed, not loaded)
    ├── fill_form.py      # Form filling script
    └── validate.py       # Validation script
```

#### Pattern 1: High-level guide with references

````markdown  theme={null}
---
name: PDF Processing
description: Extracts text and tables from PDF files, fills forms, and merges documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.
---

# PDF Processing

## Quick start

Extract text with pdfplumber:
```python
import pdfplumber
with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```

## Advanced features

**Form filling**: See [FORMS.md](FORMS.md) for complete guide
**API reference**: See [REFERENCE.md](REFERENCE.md) for all methods
**Examples**: See [EXAMPLES.md](EXAMPLES.md) for common patterns
````

Claude 只会在需要时加载 `FORMS.md`、`REFERENCE.md` 或 `EXAMPLES.md`。

#### Pattern 2: Domain-specific organization

对于覆盖多个领域的 Skills，按领域组织内容，以避免加载无关上下文。当用户询问 sales metrics 时，Claude 只需要读取与 sales 相关的 schema，而不需要 finance 或 marketing 数据。这样可以降低 token 消耗，并让上下文更聚焦。

```
bigquery-skill/
├── SKILL.md (overview and navigation)
└── reference/
    ├── finance.md (revenue, billing metrics)
    ├── sales.md (opportunities, pipeline)
    ├── product.md (API usage, features)
    └── marketing.md (campaigns, attribution)
```

````markdown SKILL.md theme={null}
# BigQuery Data Analysis

## Available datasets

**Finance**: Revenue, ARR, billing → See [reference/finance.md](reference/finance.md)
**Sales**: Opportunities, pipeline, accounts → See [reference/sales.md](reference/sales.md)
**Product**: API usage, features, adoption → See [reference/product.md](reference/product.md)
**Marketing**: Campaigns, attribution, email → See [reference/marketing.md](reference/marketing.md)

## Quick search

Find specific metrics using grep:

```bash
grep -i "revenue" reference/finance.md
grep -i "pipeline" reference/sales.md
grep -i "api usage" reference/product.md
```
````

#### Pattern 3: Conditional details

展示基础内容，并链接到高级内容：

```markdown  theme={null}
# DOCX Processing

## Creating documents

Use docx-js for new documents. See [DOCX-JS.md](DOCX-JS.md).

## Editing documents

For simple edits, modify the XML directly.

**For tracked changes**: See [REDLINING.md](REDLINING.md)
**For OOXML details**: See [OOXML.md](OOXML.md)
```

只有当用户需要这些特性时，Claude 才会读取 `REDLINING.md` 或 `OOXML.md`。

### Avoid deeply nested references

如果 reference files 再去引用其他 reference files，Claude 可能只会做部分读取。当遇到嵌套引用时，Claude 可能会使用 `head -100` 一类命令预览内容，而不是完整读取文件，从而导致信息不完整。

**让引用从 `SKILL.md` 出发最多只深入一层。** 所有 reference files 都应该直接从 `SKILL.md` 链接出去，以确保 Claude 在需要时读取完整文件。

**Bad example: Too deep**：

```markdown  theme={null}
# SKILL.md
See [advanced.md](advanced.md)...

# advanced.md
See [details.md](details.md)...

# details.md
Here's the actual information...
```

**Good example: One level deep**：

```markdown  theme={null}
# SKILL.md

**Basic usage**: [instructions in SKILL.md]
**Advanced features**: See [advanced.md](advanced.md)
**API reference**: See [reference.md](reference.md)
**Examples**: See [examples.md](examples.md)
```

### Structure longer reference files with table of contents

对于超过 100 行的 reference file，在顶部加一个目录。这样即便 Claude 只是做部分预览，也能看到完整信息范围。

**Example**：

```markdown  theme={null}
# API Reference

## Contents
- Authentication and setup
- Core methods (create, read, update, delete)
- Advanced features (batch operations, webhooks)
- Error handling patterns
- Code examples

## Authentication and setup
...

## Core methods
...
```

这样 Claude 就可以在需要时完整读取文件，或直接跳到特定章节。

关于这种基于文件系统的架构如何实现 progressive disclosure，详见下文 Advanced 部分中的 [Runtime environment](#runtime-environment)。

## Workflows and feedback loops

### Use workflows for complex tasks

把复杂操作拆成清晰、顺序化的步骤。对于特别复杂的工作流，提供一个 Claude 可以直接复制到回复里并逐项勾选的 checklist。

**Example 1: Research synthesis workflow**（适用于不含代码的 Skills）：

````markdown  theme={null}
## Research synthesis workflow

Copy this checklist and track your progress:

```
Research Progress:
- [ ] Step 1: Read all source documents
- [ ] Step 2: Identify key themes
- [ ] Step 3: Cross-reference claims
- [ ] Step 4: Create structured summary
- [ ] Step 5: Verify citations
```

**Step 1: Read all source documents**

Review each document in the `sources/` directory. Note the main arguments and supporting evidence.

**Step 2: Identify key themes**

Look for patterns across sources. What themes appear repeatedly? Where do sources agree or disagree?

**Step 3: Cross-reference claims**

For each major claim, verify it appears in the source material. Note which source supports each point.

**Step 4: Create structured summary**

Organize findings by theme. Include:
- Main claim
- Supporting evidence from sources
- Conflicting viewpoints (if any)

**Step 5: Verify citations**

Check that every claim references the correct source document. If citations are incomplete, return to Step 3.
````

这个例子展示了工作流如何适用于不需要代码的分析任务。checklist 模式适用于任何复杂的多步骤流程。

**Example 2: PDF form filling workflow**（适用于包含代码的 Skills）：

````markdown  theme={null}
## PDF form filling workflow

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Analyze the form (run analyze_form.py)
- [ ] Step 2: Create field mapping (edit fields.json)
- [ ] Step 3: Validate mapping (run validate_fields.py)
- [ ] Step 4: Fill the form (run fill_form.py)
- [ ] Step 5: Verify output (run verify_output.py)
```

**Step 1: Analyze the form**

Run: `python scripts/analyze_form.py input.pdf`

This extracts form fields and their locations, saving to `fields.json`.

**Step 2: Create field mapping**

Edit `fields.json` to add values for each field.

**Step 3: Validate mapping**

Run: `python scripts/validate_fields.py fields.json`

Fix any validation errors before continuing.

**Step 4: Fill the form**

Run: `python scripts/fill_form.py input.pdf fields.json output.pdf`

**Step 5: Verify output**

Run: `python scripts/verify_output.py output.pdf`

If verification fails, return to Step 2.
````

清晰步骤可以防止 Claude 跳过关键验证。checklist 能帮助 Claude 和你一起跟踪复杂多步骤流程的进度。

### Implement feedback loops

**Common pattern**：Run validator → fix errors → repeat

这个模式能显著提升输出质量。

**Example 1: Style guide compliance**（适用于不含代码的 Skills）：

```markdown  theme={null}
## Content review process

1. Draft your content following the guidelines in STYLE_GUIDE.md
2. Review against the checklist:
   - Check terminology consistency
   - Verify examples follow the standard format
   - Confirm all required sections are present
3. If issues found:
   - Note each issue with specific section reference
   - Revise the content
   - Review the checklist again
4. Only proceed when all requirements are met
5. Finalize and save the document
```

这个例子使用 reference documents 而非脚本来展示 validation loop 模式。这里的 “validator” 是 `STYLE_GUIDE.md`，而 Claude 通过读取并对照它来执行检查。

**Example 2: Document editing process**（适用于包含代码的 Skills）：

```markdown  theme={null}
## Document editing process

1. Make your edits to `word/document.xml`
2. **Validate immediately**: `python ooxml/scripts/validate.py unpacked_dir/`
3. If validation fails:
   - Review the error message carefully
   - Fix the issues in the XML
   - Run validation again
4. **Only proceed when validation passes**
5. Rebuild: `python ooxml/scripts/pack.py unpacked_dir/ output.docx`
6. Test the output document
```

这个 validation loop 能尽早抓住错误。

## Content guidelines

### Avoid time-sensitive information

不要包含会过时的信息：

**Bad example: Time-sensitive**（以后会错）：

```markdown  theme={null}
If you're doing this before August 2025, use the old API.
After August 2025, use the new API.
```

**Good example**（使用 “old patterns” section）：

```markdown  theme={null}
## Current method

Use the v2 API endpoint: `api.example.com/v2/messages`

## Old patterns

<details>
<summary>Legacy v1 API (deprecated 2025-08)</summary>

The v1 API used: `api.example.com/v1/messages`

This endpoint is no longer supported.
</details>
```

old patterns section 能提供历史上下文，而不会让主内容变得杂乱。

### Use consistent terminology

选定一个术语，并在整个 Skill 中保持一致：

**Good - Consistent**：

* 始终使用 “API endpoint”
* 始终使用 “field”
* 始终使用 “extract”

**Bad - Inconsistent**：

* 混用 “API endpoint”、"URL"、"API route"、"path"
* 混用 “field”、"box"、"element"、"control"
* 混用 “extract”、"pull"、"get"、"retrieve"

一致性能帮助 Claude 更好地理解和遵循说明。

## Common patterns

### Template pattern

为输出格式提供模板。具体约束程度应与你的需求相匹配。

**For strict requirements**（例如 API responses 或 data formats）：

````markdown  theme={null}
## Report structure

ALWAYS use this exact template structure:

```markdown
# [Analysis Title]

## Executive summary
[One-paragraph overview of key findings]

## Key findings
- Finding 1 with supporting data
- Finding 2 with supporting data
- Finding 3 with supporting data

## Recommendations
1. Specific actionable recommendation
2. Specific actionable recommendation
```
````

**For flexible guidance**（当适配有价值时）：

````markdown  theme={null}
## Report structure

Here is a sensible default format, but use your best judgment based on the analysis:

```markdown
# [Analysis Title]

## Executive summary
[Overview]

## Key findings
[Adapt sections based on what you discover]

## Recommendations
[Tailor to the specific context]
```

Adjust sections as needed for the specific analysis type.
````

### Examples pattern

对于那些输出质量强依赖示例的 Skills，像常规 prompting 一样提供输入 / 输出对：

````markdown  theme={null}
## Commit message format

Generate commit messages following these examples:

**Example 1:**
Input: Added user authentication with JWT tokens
Output:
```
feat(auth): implement JWT-based authentication

Add login endpoint and token validation middleware
```

**Example 2:**
Input: Fixed bug where dates displayed incorrectly in reports
Output:
```
fix(reports): correct date formatting in timezone conversion

Use UTC timestamps consistently across report generation
```

**Example 3:**
Input: Updated dependencies and refactored error handling
Output:
```
chore: update dependencies and refactor error handling

- Upgrade lodash to 4.17.21
- Standardize error response format across endpoints
```

Follow this style: type(scope): brief description, then detailed explanation.
````

示例比文字描述更能让 Claude 理解你想要的风格和细节层次。

### Conditional workflow pattern

引导 Claude 穿过决策点：

```markdown  theme={null}
## Document modification workflow

1. Determine the modification type:

   **Creating new content?** → Follow "Creation workflow" below
   **Editing existing content?** → Follow "Editing workflow" below

2. Creation workflow:
   - Use docx-js library
   - Build document from scratch
   - Export to .docx format

3. Editing workflow:
   - Unpack existing document
   - Modify XML directly
   - Validate after each change
   - Repack when complete
```

<Tip>
  如果工作流变得很长或很复杂，包含很多步骤，就考虑把它拆到单独文件中，并告诉 Claude 根据当前任务去读对应文件。
</Tip>

## Evaluation and iteration

### Build evaluations first

**在写大量文档之前，先建立 evaluations。** 这样可以确保你的 Skill 解决的是真实问题，而不是在记录想象中的问题。

**Evaluation-driven development:**

1. **Identify gaps**：在没有 Skill 的情况下，让 Claude 执行代表性任务。记录具体失败或缺失上下文
2. **Create evaluations**：构建三个用来测试这些缺口的场景
3. **Establish baseline**：测量 Claude 在没有 Skill 时的表现
4. **Write minimal instructions**：只写刚好足以填补缺口并通过评测的内容
5. **Iterate**：执行评测，与 baseline 对比，并持续改进

这种方法能确保你解决的是真实问题，而不是为可能永远不会出现的需求预先写文档。

**Evaluation structure**：

```json  theme={null}
{
  "skills": ["pdf-processing"],
  "query": "Extract all text from this PDF file and save it to output.txt",
  "files": ["test-files/document.pdf"],
  "expected_behavior": [
    "Successfully reads the PDF file using an appropriate PDF processing library or command-line tool",
    "Extracts text content from all pages in the document without missing any pages",
    "Saves the extracted text to a file named output.txt in a clear, readable format"
  ]
}
```

<Note>
  这个例子展示了一种数据驱动的 evaluation，以及简单测试 rubric。我们目前没有内置方式来运行这些 evaluations。用户可以自行创建 evaluation system。evaluations 是衡量 Skill 效果的事实标准。
</Note>

### Develop Skills iteratively with Claude

最有效的 Skill 开发过程，本身就包含 Claude。你可以用一个 Claude 实例（“Claude A”）创建 Skill，再让另一个实例（“Claude B”）来使用它。Claude A 帮你设计和改进说明，Claude B 则在真实任务中测试它们。之所以有效，是因为 Claude 模型既理解如何编写有效的 agent instructions，也理解 agents 需要什么信息。

**Creating a new Skill:**

1. **先在没有 Skill 的情况下完成一次任务**：使用普通 prompting 与 Claude A 一起解决问题。过程中，你自然会不断补充上下文、解释偏好、分享流程知识。留意哪些信息是你反复提供的。

2. **Identify the reusable pattern**：完成任务后，找出你提供过哪些对未来类似任务有用的上下文。

   **Example**：如果你一起完成了一次 BigQuery analysis，你可能提供了 table names、field definitions、filtering rules（例如 “always exclude test accounts”）以及常见 query patterns。

3. **请 Claude A 创建一个 Skill**：例如：“Create a Skill that captures this BigQuery analysis pattern we just used. Include the table schemas, naming conventions, and the rule about filtering test accounts.”

   <Tip>
     Claude 模型原生理解 Skill 的格式和结构。你不需要额外的 system prompt，也不需要一个 “writing skills” skill 才能让 Claude 帮你创建 Skills。只要直接要求 Claude 创建一个 Skill，它就会生成结构正确、包含合适 frontmatter 和 body 的 `SKILL.md` 内容。
   </Tip>

4. **Review for conciseness**：检查 Claude A 是否加入了不必要的解释。比如可以说：“Remove the explanation about what win rate means - Claude already knows that.”

5. **Improve information architecture**：请 Claude A 更有效地组织内容。例如：“Organize this so the table schema is in a separate reference file. We might add more tables later.”

6. **Test on similar tasks**：让 Claude B（一个加载了该 Skill 的新实例）在相关用例上使用它。观察 Claude B 是否能找到正确的信息、正确应用规则并成功完成任务。

7. **根据观察结果迭代**：如果 Claude B 有困难或遗漏，就把具体问题带回给 Claude A。例如：“When Claude used this Skill, it forgot to filter by date for Q4. Should we add a section about date filtering patterns?”

**Iterating on existing Skills:**

改进已有 Skills 时，同样沿用这个层级模式。你在以下角色之间来回切换：

* **与 Claude A 协作**（帮助你改进 Skill 的专家）
* **用 Claude B 测试**（实际使用 Skill 完成工作的 agent）
* **观察 Claude B 的行为**，再把洞察带回给 Claude A

1. **在真实工作流中使用 Skill**：给 Claude B（已加载 Skill）真实任务，而不是测试题

2. **观察 Claude B 的行为**：记录它在哪些地方卡住、成功，或做出意外选择

   **Example observation**：“When I asked Claude B for a regional sales report, it wrote the query but forgot to filter out test accounts, even though the Skill mentions this rule.”

3. **回到 Claude A 改进**：分享当前的 `SKILL.md` 并说明你的观察。例如：“I noticed Claude B forgot to filter test accounts when I asked for a regional report. The Skill mentions filtering, but maybe it's not prominent enough?”

4. **Review Claude A's suggestions**：Claude A 可能会建议把规则放得更显眼，使用更强语气，比如 `MUST filter` 而不是 `always filter`，或者调整 workflow section 的结构。

5. **Apply and test changes**：根据 Claude A 的建议更新 Skill，然后再用 Claude B 针对类似请求测试一次

6. **Repeat based on usage**：随着新场景不断出现，持续进行 observe-refine-test 循环。每一轮都是基于真实 agent 行为，而不是基于假设来改进 Skill。

**Gathering team feedback:**

1. 把 Skills 分享给队友并观察他们如何使用
2. 问：Skill 是否会在预期时机触发？说明是否清楚？还缺什么？
3. 纳入反馈，以弥补你自己使用模式中的盲点

**Why this approach works**：Claude A 理解 agent 需要什么，你提供领域知识，Claude B 通过真实使用暴露缺口，而迭代式改进则基于观察到的行为而非想象中的问题不断增强 Skill。

### Observe how Claude navigates Skills

在迭代 Skills 时，注意 Claude 实际是如何使用它们的。重点观察：

* **Unexpected exploration paths**：Claude 是否以你未预料的顺序读取文件？这可能说明你的结构并没有你想得那样直观
* **Missed connections**：Claude 是否没能跟进某些重要文件的引用？说明链接可能还不够明确或不够显眼
* **Overreliance on certain sections**：如果 Claude 总是反复读取某个文件，考虑是否应把该内容移入主 `SKILL.md`
* **Ignored content**：如果 Claude 从不访问某个打包文件，说明它可能不必要，或者在主说明中没有被有效提示

根据这些观察来迭代，而不是根据假设。Skill metadata 中的 `name` 和 `description` 尤其关键。Claude 会用它们来决定当前任务是否应该触发该 Skill。确保它们清楚说明了 Skill 做什么以及何时应使用。

## Anti-patterns to avoid

### Avoid Windows-style paths

即使在 Windows 上，也始终使用正斜杠：

* ✓ **Good**：`scripts/helper.py`, `reference/guide.md`
* ✗ **Avoid**：`scripts\helper.py`, `reference\guide.md`

Unix 风格路径可跨平台工作，而 Windows 风格路径会在 Unix 系统上报错。

### Avoid offering too many options

除非必要，不要同时给出多种方法：

````markdown  theme={null}
**Bad example: Too many choices** (confusing):
"You can use pypdf, or pdfplumber, or PyMuPDF, or pdf2image, or..."

**Good example: Provide a default** (with escape hatch):
"Use pdfplumber for text extraction:
```python
import pdfplumber
```

For scanned PDFs requiring OCR, use pdf2image with pytesseract instead."
````

## Advanced: Skills with executable code

下面这些章节聚焦于包含可执行脚本的 Skills。如果你的 Skill 只包含 markdown instructions，请直接跳到 [Checklist for effective Skills](#checklist-for-effective-skills)。

### Solve, don't punt

在为 Skills 编写脚本时，要处理错误条件，而不是把问题甩给 Claude。

**Good example: Handle errors explicitly**：

```python  theme={null}
def process_file(path):
    """Process a file, creating it if it doesn't exist."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        # Create file with default content instead of failing
        print(f"File {path} not found, creating default")
        with open(path, 'w') as f:
            f.write('')
        return ''
    except PermissionError:
        # Provide alternative instead of failing
        print(f"Cannot access {path}, using default")
        return ''
```

**Bad example: Punt to Claude**：

```python  theme={null}
def process_file(path):
    # Just fail and let Claude figure it out
    return open(path).read()
```

配置参数也应有合理解释和文档说明，以避免 “voodoo constants”（Ousterhout 定律）。如果你自己都不知道正确值是什么，Claude 又怎么会知道？

**Good example: Self-documenting**：

```python  theme={null}
# HTTP requests typically complete within 30 seconds
# Longer timeout accounts for slow connections
REQUEST_TIMEOUT = 30

# Three retries balances reliability vs speed
# Most intermittent failures resolve by the second retry
MAX_RETRIES = 3
```

**Bad example: Magic numbers**：

```python  theme={null}
TIMEOUT = 47  # Why 47?
RETRIES = 5   # Why 5?
```

### Provide utility scripts

即使 Claude 自己也能写脚本，预先提供好脚本仍然有明显优势：

**Benefits of utility scripts**：

* 比生成代码更可靠
* 节省 tokens（无需把代码放进上下文）
* 节省时间（无需再生成代码）
* 保证多次使用的一致性

<img src="https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-executable-scripts.png?fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=4bbc45f2c2e0bee9f2f0d5da669bad00" alt="Bundling executable scripts alongside instruction files" data-og-width="2048" width="2048" data-og-height="1154" height="1154" data-path="images/agent-skills-executable-scripts.png" data-optimize="true" data-opv="3" srcset="https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-executable-scripts.png?w=280&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=9a04e6535a8467bfeea492e517de389f 280w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-executable-scripts.png?w=560&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=e49333ad90141af17c0d7651cca7216b 560w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-executable-scripts.png?w=840&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=954265a5df52223d6572b6214168c428 840w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-executable-scripts.png?w=1100&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=2ff7a2d8f2a83ee8af132b29f10150fd 1100w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-executable-scripts.png?w=1650&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=48ab96245e04077f4d15e9170e081cfb 1650w, https://mintcdn.com/anthropic-claude-docs/4Bny2bjzuGBK7o00/images/agent-skills-executable-scripts.png?w=2500&fit=max&auto=format&n=4Bny2bjzuGBK7o00&q=85&s=0301a6c8b3ee879497cc5b5483177c90 2500w" />

上图展示了可执行脚本如何与说明文件协同工作。说明文件（如 `forms.md`）引用脚本，而 Claude 可以在不把脚本内容加载进上下文的情况下直接执行它。

**Important distinction**：在说明中要明确，Claude 应该：

* **执行脚本**（最常见）："Run `analyze_form.py` to extract fields"
* **把脚本当作参考阅读**（用于复杂逻辑）："See `analyze_form.py` for the field extraction algorithm"

对于大多数 utility scripts，执行优于阅读，因为它更可靠、更高效。关于脚本执行的机制，详见下文的 [Runtime environment](#runtime-environment)。

**Example**：

````markdown  theme={null}
## Utility scripts

**analyze_form.py**: Extract all form fields from PDF

```bash
python scripts/analyze_form.py input.pdf > fields.json
```

Output format:
```json
{
  "field_name": {"type": "text", "x": 100, "y": 200},
  "signature": {"type": "sig", "x": 150, "y": 500}
}
```

**validate_boxes.py**: Check for overlapping bounding boxes

```bash
python scripts/validate_boxes.py fields.json
# Returns: "OK" or lists conflicts
```

**fill_form.py**: Apply field values to PDF

```bash
python scripts/fill_form.py input.pdf fields.json output.pdf
```
````

### Use visual analysis

当输入可以渲染成图像时，让 Claude 进行视觉分析：

````markdown  theme={null}
## Form layout analysis

1. Convert PDF to images:
   ```bash
   python scripts/pdf_to_images.py form.pdf
   ```

2. Analyze each page image to identify form fields
3. Claude can see field locations and types visually
````

<Note>
  在这个例子中，你需要自己编写 `pdf_to_images.py` 脚本。
</Note>

Claude 的视觉能力有助于理解布局和结构。

### Create verifiable intermediate outputs

当 Claude 执行复杂、开放式任务时，它可能会出错。“plan-validate-execute” 模式通过让 Claude 先生成结构化计划，再用脚本验证计划，最后才执行，从而尽早发现错误。

**Example**：设想你让 Claude 根据电子表格更新 PDF 中的 50 个表单字段。如果没有验证，Claude 可能会引用不存在的字段、制造冲突值、漏掉必填字段，或错误应用更新。

**Solution**：使用上面展示过的 workflow 模式（PDF form filling），但在执行前增加一个中间 `changes.json` 文件，并先对它做验证。工作流就变成：analyze → **create plan file** → **validate plan** → execute → verify。

**Why this pattern works:**

* **Catches errors early**：在真正应用改动前先发现问题
* **Machine-verifiable**：脚本提供客观验证
* **Reversible planning**：Claude 可以只迭代计划，而不触碰原文件
* **Clear debugging**：错误信息能定位到具体问题

**When to use**：批量操作、破坏性改动、复杂校验规则、高风险操作。

**Implementation tip**：让验证脚本输出详细且具体的错误信息，例如：`Field 'signature_date' not found. Available fields: customer_name, order_total, signature_date_signed`，这样 Claude 更容易修复。

### Package dependencies

Skills 会运行在有平台限制的代码执行环境中：

* **claude.ai**：可以从 npm 和 PyPI 安装包，也可以从 GitHub 拉取仓库
* **Anthropic API**：没有网络访问，也不能在运行时安装依赖

把必需依赖列在 `SKILL.md` 中，并在 [code execution tool documentation](/en/docs/agents-and-tools/tool-use/code-execution-tool) 中确认它们可用。

### Runtime environment

Skills 运行在具备文件系统访问、bash 命令和代码执行能力的环境中。关于该架构的概念解释，见总览中的 [The Skills architecture](/en/docs/agents-and-tools/agent-skills/overview#the-skills-architecture)。

**How this affects your authoring:**

**How Claude accesses Skills:**

1. **Metadata pre-loaded**：启动时，所有 Skills 的 YAML frontmatter 中的 name 和 description 会被加载进 system prompt
2. **Files read on-demand**：Claude 会在需要时使用 bash Read tools 从文件系统读取 `SKILL.md` 和其他文件
3. **Scripts executed efficiently**：utility scripts 可以通过 bash 直接执行，而无需将全部内容载入上下文。只有脚本输出会消耗 tokens
4. **No context penalty for large files**：reference files、数据或文档，在真正读取前不会消耗上下文 token

* **File paths matter**：Claude 会像浏览文件系统一样浏览你的 skill 目录。使用正斜杠（`reference/guide.md`），不要使用反斜杠
* **Name files descriptively**：使用能表明内容的文件名，例如 `form_validation_rules.md`，而不是 `doc2.md`
* **Organize for discovery**：按领域或特性组织目录
  * Good: `reference/finance.md`, `reference/sales.md`
  * Bad: `docs/file1.md`, `docs/file2.md`
* **Bundle comprehensive resources**：可以包含完整 API docs、大量示例、大型数据集；在真正访问前不产生上下文成本
* **Prefer scripts for deterministic operations**：写 `validate_form.py`，而不是让 Claude 临时生成验证代码
* **Make execution intent clear**：
  * `Run analyze_form.py to extract fields`（执行）
  * `See analyze_form.py for the extraction algorithm`（作为参考阅读）
* **Test file access patterns**：通过真实请求验证 Claude 是否能顺利导航你的目录结构

**Example:**

```
bigquery-skill/
├── SKILL.md (overview, points to reference files)
└── reference/
    ├── finance.md (revenue metrics)
    ├── sales.md (pipeline data)
    └── product.md (usage analytics)
```

当用户询问 revenue 时，Claude 会读取 `SKILL.md`，看到对 `reference/finance.md` 的引用，并通过 bash 仅读取那个文件。`sales.md` 和 `product.md` 仍留在文件系统中，在被需要前不会消耗任何上下文 token。这种基于文件系统的模型，正是 progressive disclosure 的基础。Claude 可以导航并选择性加载每个任务真正需要的内容。

技术架构的完整细节见 Skills overview 中的 [How Skills work](/en/docs/agents-and-tools/agent-skills/overview#how-skills-work)。

### MCP tool references

如果你的 Skill 使用 MCP（Model Context Protocol）tools，始终使用完整限定工具名，以避免 “tool not found” 错误。

**Format**：`ServerName:tool_name`

**Example**：

```markdown  theme={null}
Use the BigQuery:bigquery_schema tool to retrieve table schemas.
Use the GitHub:create_issue tool to create issues.
```

其中：

* `BigQuery` 和 `GitHub` 是 MCP server 名称
* `bigquery_schema` 和 `create_issue` 是各自 server 中的 tool 名称

如果没有 server 前缀，Claude 可能无法定位工具，尤其是在存在多个 MCP servers 时。

### Avoid assuming tools are installed

不要假设依赖已经存在：

````markdown  theme={null}
**Bad example: Assumes installation**:
"Use the pdf library to process the file."

**Good example: Explicit about dependencies**:
"Install required package: `pip install pypdf`

Then use it:
```python
from pypdf import PdfReader
reader = PdfReader("file.pdf")
```"
````

## Technical notes

### YAML frontmatter requirements

`SKILL.md` 的 frontmatter 需要 `name`（最多 64 个字符）和 `description`（最多 1024 个字符）字段。完整结构见 [Skills overview](/en/docs/agents-and-tools/agent-skills/overview#skill-structure)。

### Token budgets

为了最佳性能，请将 `SKILL.md` 正文控制在 500 行以内。如果内容超过这一限制，就使用前面介绍的 progressive disclosure 模式拆分到独立文件中。关于架构细节，见 [Skills overview](/en/docs/agents-and-tools/agent-skills/overview#how-skills-work)。

## Checklist for effective Skills

在分享一个 Skill 前，请确认：

### Core quality

* [ ] Description 具体并包含关键术语
* [ ] Description 同时包含 Skill 做什么以及何时使用
* [ ] `SKILL.md` 正文少于 500 行
* [ ] 额外细节已拆到单独文件（若需要）
* [ ] 不含时效性信息（或已放在 “old patterns” section）
* [ ] 全文术语一致
* [ ] 示例具体，而非抽象
* [ ] 文件引用只深入一层
* [ ] 已正确使用 progressive disclosure
* [ ] workflows 具有清晰步骤

### Code and scripts

* [ ] 脚本是为了解决问题，而不是把问题甩给 Claude
* [ ] 错误处理明确且有帮助
* [ ] 没有 “voodoo constants”（所有值都有合理说明）
* [ ] 必需依赖已在说明中列出并确认可用
* [ ] 脚本文档清晰
* [ ] 没有 Windows 风格路径（全部使用正斜杠）
* [ ] 对关键操作有 validation/verification 步骤
* [ ] 对质量关键任务包含 feedback loops

### Testing

* [ ] 至少创建了三个 evaluations
* [ ] 使用 Haiku、Sonnet 和 Opus 做过测试
* [ ] 在真实使用场景中测试过
* [ ] 已纳入团队反馈（如果适用）

## Next steps

<CardGroup cols={2}>
  <Card title="Get started with Agent Skills" icon="rocket" href="/en/docs/agents-and-tools/agent-skills/quickstart">
    创建你的第一个 Skill
  </Card>

  <Card title="Use Skills in Claude Code" icon="terminal" href="/en/docs/claude-code/skills">
    在 Claude Code 中创建和管理 Skills
  </Card>

  <Card title="Use Skills with the API" icon="code" href="/en/api/skills-guide">
    以编程方式上传和使用 Skills
  </Card>
</CardGroup>
