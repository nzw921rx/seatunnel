```markdown
# seatunnel Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill covers the core development patterns and conventions found in the `seatunnel` Java codebase. It documents file organization, import/export styles, commit message patterns, and testing approaches to help contributors write consistent, maintainable code. While no specific framework is detected, the repository follows clear conventions for file naming, code structure, and testing.

## Coding Conventions

### File Naming
- **Style:** `snake_case`
- **Example:**  
  ```java
  // Good
  my_module.java
  data_processor.java
  ```

### Imports
- **Style:** Relative imports are used.
- **Example:**  
  ```java
  import my_package.my_module;
  import utils.helper_functions;
  ```

### Exports
- **Style:** Named exports are preferred.
- **Example:**  
  ```java
  public class DataProcessor {
      // ...
  }
  ```

### Commit Messages
- **Type:** Freeform, with some using the `Test` prefix.
- **Average Length:** ~42 characters.
- **Example:**  
  ```
  Test add new data source connector
  Fix bug in data transformation logic
  ```

## Workflows

### Adding a New Module
**Trigger:** When you need to introduce a new feature or logical component.
**Command:** `/add-module`

1. Create a new file using `snake_case` naming (e.g., `new_feature.java`).
2. Use relative imports to include dependencies.
3. Export your main class with a named export.
4. Write a commit message summarizing your addition.

### Refactoring Existing Code
**Trigger:** When improving code readability or maintainability.
**Command:** `/refactor`

1. Identify the target file(s) and functions.
2. Refactor code, maintaining `snake_case` file naming.
3. Update imports/exports as needed.
4. Test changes locally.
5. Commit with a clear, concise message.

### Writing and Running Tests
**Trigger:** When adding new features or fixing bugs.
**Command:** `/test`

1. Create a test file matching the pattern `*.test.ts`.
2. Write tests for new or changed functionality.
3. Run tests using the project's test runner (framework unspecified).
4. Commit with a message prefixed by `Test` if appropriate.

## Testing Patterns

- **Framework:** Not explicitly detected.
- **Test File Pattern:** `*.test.ts`
- **Example:**  
  ```typescript
  // my_module.test.ts
  import { myFunction } from './my_module';

  test('should process data correctly', () => {
      // test logic here
  });
  ```
- **Best Practice:** Prefix test-related commits with `Test` for clarity.

## Commands
| Command        | Purpose                                           |
|----------------|---------------------------------------------------|
| /add-module    | Scaffold and add a new module following conventions|
| /refactor      | Refactor code while maintaining codebase standards |
| /test          | Write and run tests for your code changes          |
```