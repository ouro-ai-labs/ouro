"""Prompts for composition assessment and orchestration.

These prompts enable the agent to dynamically decide how to decompose
complex tasks and what aspects to explore.
"""

COMPOSITION_ASSESSMENT_PROMPT = """<role>
You are analyzing a task to determine the optimal execution strategy.
</role>

<task>
{task}
</task>

<context>
Working directory: {working_directory}
Available tools: {available_tools}
</context>

<instructions>
Analyze the task and decide whether to:
1. Execute directly (simple tasks that need 1-3 tool calls)
2. Decompose using composition patterns (complex multi-step tasks)

If decomposition is needed, determine:
- What aspects need exploration BEFORE planning
- The exploration aspects should be SPECIFIC to this task, not generic templates

OUTPUT FORMAT (JSON):
{{
  "should_compose": true/false,
  "pattern": "none" | "plan_execute" | "parallel_explore",
  "exploration_aspects": [
    {{
      "name": "short_identifier",
      "description": "What to explore and why",
      "focus_areas": ["specific question 1", "specific question 2"]
    }}
  ],
  "reasoning": "Brief explanation of your decision"
}}

GUIDELINES:
- Use "none" for simple tasks (file read, single edit, quick search)
- Use "plan_execute" for complex modifications requiring context
- Use "parallel_explore" for research/analysis tasks
- Exploration aspects should be TASK-SPECIFIC, not generic
- Maximum 4 exploration aspects

EXAMPLES:

Task: "Read the config.py file"
{{
  "should_compose": false,
  "pattern": "none",
  "exploration_aspects": [],
  "reasoning": "Simple file read operation"
}}

Task: "Refactor the authentication system to use JWT"
{{
  "should_compose": true,
  "pattern": "plan_execute",
  "exploration_aspects": [
    {{
      "name": "current_auth",
      "description": "Understand current authentication implementation",
      "focus_areas": ["Where is auth handled?", "What auth methods exist?", "Session management?"]
    }},
    {{
      "name": "jwt_integration",
      "description": "Identify JWT integration points and dependencies",
      "focus_areas": ["Existing JWT libraries?", "Token storage strategy?", "Refresh token handling?"]
    }}
  ],
  "reasoning": "Complex refactoring requiring understanding of existing auth and planning for JWT migration"
}}
</instructions>

Analyze and respond with JSON:"""


EXPLORATION_ASPECT_PROMPT = """<role>
You are exploring a specific aspect of the codebase to inform planning.
</role>

<main_task>
{main_task}
</main_task>

<exploration_aspect>
Name: {aspect_name}
Description: {aspect_description}
Focus Areas:
{focus_areas}
</exploration_aspect>

<instructions>
1. Use ONLY read-only tools:
   - glob_files: Find files by pattern
   - grep_content: Search file contents
   - read_file: Read file contents
   - code_navigator: Navigate code structure

2. Focus SPECIFICALLY on the exploration aspect
3. Answer the focus area questions
4. Note any constraints or dependencies discovered
5. Do NOT make changes - just gather information

OUTPUT:
Provide a structured summary of your findings addressing each focus area.
</instructions>

Explore and report:"""


SYNTHESIS_PROMPT = """<role>
You are synthesizing exploration results into actionable context for planning.
</role>

<main_task>
{main_task}
</main_task>

<exploration_results>
{exploration_results}
</exploration_results>

<instructions>
Create a concise synthesis that:
1. Highlights key findings relevant to the main task
2. Identifies constraints and dependencies
3. Notes potential challenges or blockers
4. Provides recommendations for the execution plan

Keep it focused and actionable - this will inform the planning phase.
</instructions>

Synthesis:"""


SUBTASK_ASSESSMENT_PROMPT = """<role>
You are evaluating whether a subtask should be delegated to a sub-agent.
</role>

<current_context>
Main task: {main_task}
Current step: {current_step}
Depth: {current_depth}/{max_depth}
Agent count: {agent_count}/{max_agents}
</current_context>

<subtask>
{subtask_description}
</subtask>

<instructions>
Decide whether to:
1. Execute inline (simple, 1-2 tool calls)
2. Delegate to sub-agent (complex, would clutter context)

Consider:
- Complexity of the subtask
- Impact on current context
- Resource limits (depth, agent count)
- Whether isolation benefits outweigh overhead

OUTPUT FORMAT (JSON):
{{
  "should_delegate": true/false,
  "reasoning": "Brief explanation",
  "tool_filter": ["tool1", "tool2"] or null
}}
</instructions>

Analyze:"""
