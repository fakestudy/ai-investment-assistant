# Defense-in-Depth Validation

## 概览

当你修复一个由无效数据导致的 bug 时，只在一个地方加校验会让人觉得“已经足够”。但这个单点检查可能会被其他代码路径、重构或 mocks 绕过。

**核心原则：** 在数据经过的**每一层**都做验证。要让这个 bug 从结构上变得不可能发生。

## 为什么要多层防御

单点验证：“We fixed the bug”  
多层验证：“We made the bug impossible”

不同层会捕获不同情况：
- 入口校验能抓住大多数 bug
- 业务逻辑能抓住边界情况
- 环境保护能避免特定上下文下的危险操作
- 调试日志能在其他层失败时保留证据

## 四层防御

### Layer 1: Entry Point Validation
**目的：** 在 API 边界拒绝明显无效的输入

```typescript
function createProject(name: string, workingDirectory: string) {
  if (!workingDirectory || workingDirectory.trim() === '') {
    throw new Error('workingDirectory cannot be empty');
  }
  if (!existsSync(workingDirectory)) {
    throw new Error(`workingDirectory does not exist: ${workingDirectory}`);
  }
  if (!statSync(workingDirectory).isDirectory()) {
    throw new Error(`workingDirectory is not a directory: ${workingDirectory}`);
  }
  // ... proceed
}
```

### Layer 2: Business Logic Validation
**目的：** 确保数据对当前操作来说是合理的

```typescript
function initializeWorkspace(projectDir: string, sessionId: string) {
  if (!projectDir) {
    throw new Error('projectDir required for workspace initialization');
  }
  // ... proceed
}
```

### Layer 3: Environment Guards
**目的：** 防止在特定上下文中执行危险操作

```typescript
async function gitInit(directory: string) {
  // In tests, refuse git init outside temp directories
  if (process.env.NODE_ENV === 'test') {
    const normalized = normalize(resolve(directory));
    const tmpDir = normalize(resolve(tmpdir()));

    if (!normalized.startsWith(tmpDir)) {
      throw new Error(
        `Refusing git init outside temp dir during tests: ${directory}`
      );
    }
  }
  // ... proceed
}
```

### Layer 4: Debug Instrumentation
**目的：** 捕获上下文，便于事后分析

```typescript
async function gitInit(directory: string) {
  const stack = new Error().stack;
  logger.debug('About to git init', {
    directory,
    cwd: process.cwd(),
    stack,
  });
  // ... proceed
}
```

## 如何应用这个模式

当你发现一个 bug：

1. **追踪数据流** - 错误值来自哪里？在哪里被使用？
2. **列出所有检查点** - 把数据经过的每个点都列出来
3. **在每一层添加验证** - 入口、业务、环境、调试
4. **测试每一层** - 试着绕过 layer 1，确认 layer 2 仍然能拦住

## 来自会话的示例

Bug：空的 `projectDir` 导致在源码目录执行 `git init`

**数据流：**
1. Test setup → 空字符串
2. `Project.create(name, '')`
3. `WorkspaceManager.createWorkspace('')`
4. `git init` 在 `process.cwd()` 中执行

**新增的四层防御：**
- Layer 1: `Project.create()` 校验非空 / 存在 / 可写
- Layer 2: `WorkspaceManager` 校验 projectDir 非空
- Layer 3: `WorktreeManager` 在测试中拒绝在 tmpdir 之外执行 `git init`
- Layer 4: `git init` 前记录 stack trace

**结果：** 1847 个测试全部通过，bug 无法再被复现

## 关键洞察

四层防御全部都需要。在测试中，每一层都抓到了其他层漏掉的问题：
- 不同代码路径会绕过入口校验
- Mocks 会绕过业务逻辑检查
- 不同平台上的边界情况需要环境保护
- 调试日志能识别结构性误用

**不要停在一个验证点。** 要在每一层都加检查。
