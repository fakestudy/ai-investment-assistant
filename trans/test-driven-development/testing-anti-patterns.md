# Testing Anti-Patterns

**在以下情况下加载此参考：** 编写或修改测试、添加 mocks，或当你想在生产代码中加入仅供测试使用的方法时。

## 概览

测试必须验证真实行为，而不是 mock 行为。Mock 的作用是隔离，不是被测试对象本身。

**核心原则：** 测代码做了什么，不要测 mocks 做了什么。

**严格遵循 TDD 可以防止这些 anti-patterns。**

## 铁律

```
1. NEVER test mock behavior
2. NEVER add test-only methods to production classes
3. NEVER mock without understanding dependencies
```

## Anti-Pattern 1: Testing Mock Behavior

**错误做法：**
```typescript
// ❌ BAD: Testing that the mock exists
test('renders sidebar', () => {
  render(<Page />);
  expect(screen.getByTestId('sidebar-mock')).toBeInTheDocument();
});
```

**为什么错：**
- 你验证的是 mock 是否工作，不是组件是否工作
- 测试会因为 mock 存在而通过，因为 mock 不存在而失败
- 它无法告诉你任何真实行为信息

**你的人类协作伙伴可能会这样纠正：** “Are we testing the behavior of a mock?”

**正确做法：**
```typescript
// ✅ GOOD: Test real component or don't mock it
test('renders sidebar', () => {
  render(<Page />);  // Don't mock sidebar
  expect(screen.getByRole('navigation')).toBeInTheDocument();
});

// OR if sidebar must be mocked for isolation:
// Don't assert on the mock - test Page's behavior with sidebar present
```

### Gate Function

```
BEFORE asserting on any mock element:
  Ask: "Am I testing real component behavior or just mock existence?"

  IF testing mock existence:
    STOP - Delete the assertion or unmock the component

  Test real behavior instead
```

## Anti-Pattern 2: Test-Only Methods in Production

**错误做法：**
```typescript
// ❌ BAD: destroy() only used in tests
class Session {
  async destroy() {  // Looks like production API!
    await this._workspaceManager?.destroyWorkspace(this.id);
    // ... cleanup
  }
}

// In tests
afterEach(() => session.destroy());
```

**为什么错：**
- 生产类被测试专用代码污染了
- 如果在生产中被误调用会有风险
- 违背 YAGNI 和关注点分离
- 混淆了对象生命周期与实体生命周期

**正确做法：**
```typescript
// ✅ GOOD: Test utilities handle test cleanup
// Session has no destroy() - it's stateless in production

// In test-utils/
export async function cleanupSession(session: Session) {
  const workspace = session.getWorkspaceInfo();
  if (workspace) {
    await workspaceManager.destroyWorkspace(workspace.id);
  }
}

// In tests
afterEach(() => cleanupSession(session));
```

### Gate Function

```
BEFORE adding any method to production class:
  Ask: "Is this only used by tests?"

  IF yes:
    STOP - Don't add it
    Put it in test utilities instead

  Ask: "Does this class own this resource's lifecycle?"

  IF no:
    STOP - Wrong class for this method
```

## Anti-Pattern 3: Mocking Without Understanding

**错误做法：**
```typescript
// ❌ BAD: Mock breaks test logic
test('detects duplicate server', () => {
  // Mock prevents config write that test depends on!
  vi.mock('ToolCatalog', () => ({
    discoverAndCacheTools: vi.fn().mockResolvedValue(undefined)
  }));

  await addServer(config);
  await addServer(config);  // Should throw - but won't!
});
```

**为什么错：**
- 你 mock 的方法带有测试依赖的副作用（写配置）
- 为了“保险起见”而过度 mock，反而破坏了真实行为
- 测试会因错误原因通过，或莫名其妙失败

**正确做法：**
```typescript
// ✅ GOOD: Mock at correct level
test('detects duplicate server', () => {
  // Mock the slow part, preserve behavior test needs
  vi.mock('MCPServerManager'); // Just mock slow server startup

  await addServer(config);  // Config written
  await addServer(config);  // Duplicate detected ✓
});
```

### Gate Function

```
BEFORE mocking any method:
  STOP - Don't mock yet

  1. Ask: "What side effects does the real method have?"
  2. Ask: "Does this test depend on any of those side effects?"
  3. Ask: "Do I fully understand what this test needs?"

  IF depends on side effects:
    Mock at lower level (the actual slow/external operation)
    OR use test doubles that preserve necessary behavior
    NOT the high-level method the test depends on

  IF unsure what test depends on:
    Run test with real implementation FIRST
    Observe what actually needs to happen
    THEN add minimal mocking at the right level

  Red flags:
    - "I'll mock this to be safe"
    - "This might be slow, better mock it"
    - Mocking without understanding the dependency chain
```

## Anti-Pattern 4: Incomplete Mocks

**错误做法：**
```typescript
// ❌ BAD: Partial mock - only fields you think you need
const mockResponse = {
  status: 'success',
  data: { userId: '123', name: 'Alice' }
  // Missing: metadata that downstream code uses
};

// Later: breaks when code accesses response.metadata.requestId
```

**为什么错：**
- **局部 mock 会隐藏结构性假设** - 你只 mock 了自己已知的字段
- **下游代码可能依赖你没包含的字段** - 会产生静默失败
- **测试通过但集成失败** - mock 不完整，而真实 API 完整
- **虚假的信心** - 这个测试无法证明真实行为

**铁律：** Mock 的必须是现实中存在的**完整数据结构**，而不只是当前测试直接用到的字段。

**正确做法：**
```typescript
// ✅ GOOD: Mirror real API completeness
const mockResponse = {
  status: 'success',
  data: { userId: '123', name: 'Alice' },
  metadata: { requestId: 'req-789', timestamp: 1234567890 }
  // All fields real API returns
};
```

### Gate Function

```
BEFORE creating mock responses:
  Check: "What fields does the real API response contain?"

  Actions:
    1. Examine actual API response from docs/examples
    2. Include ALL fields system might consume downstream
    3. Verify mock matches real response schema completely

  Critical:
    If you're creating a mock, you must understand the ENTIRE structure
    Partial mocks fail silently when code depends on omitted fields

  If uncertain: Include all documented fields
```

## Anti-Pattern 5: Integration Tests as Afterthought

**错误做法：**
```
✅ Implementation complete
❌ No tests written
"Ready for testing"
```

**为什么错：**
- Testing 是实现的一部分，不是可选的收尾步骤
- 如果使用 TDD，本来会更早发现这个问题
- 没有测试，就不能声称已经完成

**正确做法：**
```
TDD cycle:
1. Write failing test
2. Implement to pass
3. Refactor
4. THEN claim complete
```

## 当 Mocks 变得过于复杂时

**警示信号：**
- Mock setup 比测试逻辑还长
- 为了让测试通过而什么都 mock
- Mocks 缺少真实组件拥有的方法
- Mock 一改，测试就碎

**你的人类协作伙伴可能会问：** “Do we need to be using a mock here?”

**可以考虑：** 与其写复杂 mocks，不如直接用真实组件做 integration tests，往往更简单。

## TDD 如何防止这些 Anti-Patterns

**为什么 TDD 有帮助：**
1. **先写测试** → 迫使你先想清楚自己到底在测什么
2. **看着它失败** → 确认这个测试在测真实行为，而不是 mocks
3. **最小实现** → 避免测试专用方法混入生产代码
4. **真实依赖先跑通** → 你会在开始 mock 之前搞清楚测试真正需要什么

**如果你在测 mock 行为，说明你已经违背了 TDD** —— 你在测试先失败于真实代码之前，就提前加入了 mocks。

## 快速参考

| Anti-Pattern | Fix |
|--------------|-----|
| 对 mock 元素做断言 | 测真实组件，或取消 mock |
| 在生产代码里加测试专用方法 | 移到 test utilities |
| 不理解依赖就 mock | 先理解依赖，再做最小 mock |
| 不完整的 mocks | 完整镜像真实 API |
| 把测试当成事后补充 | TDD - tests first |
| 过于复杂的 mocks | 考虑 integration tests |

## 危险信号

- 断言里检查 `*-mock` test IDs
- 某些方法只在 test 文件中被调用
- Mock setup 占了测试的 50% 以上
- 去掉 mock 后测试就失败
- 你说不清为什么需要这个 mock
- 只是“为了保险”而 mock

## 最后一句话

**Mocks 是用于隔离的工具，不是被测试对象。**

如果 TDD 暴露出你在测试 mock 行为，那说明你已经走偏了。

修正方式：去测真实行为，或者反过来问自己，为什么这里非要 mock。
