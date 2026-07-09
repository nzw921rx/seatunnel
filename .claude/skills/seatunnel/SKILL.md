```markdown
# seatunnel Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the `seatunnel` Java codebase. You'll learn how to structure files, write imports and exports, follow commit message conventions, and understand the testing approach. This guide also provides step-by-step workflows and suggested commands to streamline common development tasks.

## Coding Conventions

### File Naming
- Use **PascalCase** for file names.
  - Example: `DataProcessor.java`, `StreamHandler.java`

### Import Style
- Use **relative imports** within the codebase.
  - Example:
    ```java
    import com.seatunnel.core.DataProcessor;
    ```

### Export Style
- Use **named exports** for classes and functions.
  - Example:
    ```java
    public class DataProcessor {
        // class implementation
    }
    ```

### Commit Message Patterns
- Commit messages are **freeform** but often start with a prefix such as `Fix`.
- Average commit message length: ~46 characters.
  - Example: `Fix: handle null pointer in StreamHandler`

## Workflows

### Fixing a Bug
**Trigger:** When you identify and resolve a bug in the codebase.
**Command:** `/fix-bug`

1. Identify the bug and create a new branch for your fix.
2. Make the necessary code changes following the coding conventions.
3. Write a commit message prefixed with `Fix`, describing the issue.
   - Example: `Fix: correct data parsing in DataProcessor`
4. Push your branch and open a pull request for review.

### Adding a New Feature
**Trigger:** When implementing a new feature or module.
**Command:** `/add-feature`

1. Create a new branch for your feature.
2. Name new files using PascalCase.
3. Use relative imports for dependencies.
4. Export new classes or functions using named exports.
5. Write clear, descriptive commit messages.
6. Push your branch and open a pull request.

## Testing Patterns

- **Framework:** Unknown (not detected in analysis).
- **Test File Pattern:** Test files use the `*.test.ts` naming convention, suggesting some TypeScript-based tests may exist alongside Java code.
  - Example: `DataProcessor.test.ts`
- **Best Practice:** Place test files alongside the code they test or in a dedicated `tests` directory.

## Commands
| Command      | Purpose                                 |
|--------------|-----------------------------------------|
| /fix-bug     | Start the bug fixing workflow           |
| /add-feature | Start the new feature development flow  |
```
