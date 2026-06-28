# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json
import logging
from typing import Any, Generator
from pydantic import BaseModel

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools import AgentTool
from google.adk.workflow import Workflow, node, START
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App
from google.genai import types

from app.config import config

# Ensure Vertex AI mode matches universal config
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

# Initialize model
gemini_model = Gemini(model=config.model)

# -----------------------------------------------------------------------------
# Structured Outputs
# -----------------------------------------------------------------------------
class MealPlan(BaseModel):
    recipe_name: str
    ingredients: list[str]
    instructions: list[str]
    dietary_notes: str

class ShoppingList(BaseModel):
    items: list[str]
    estimated_cost: str

# -----------------------------------------------------------------------------
# MCP Toolset Configuration
# -----------------------------------------------------------------------------
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=[
                "run",
                "--with",
                "mcp",
                "python",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py"),
            ],
        ),
    )
)

# -----------------------------------------------------------------------------
# Specialized Sub-Agents
# -----------------------------------------------------------------------------
meal_planner_agent = LlmAgent(
    name="meal_planner_agent",
    model=gemini_model,
    instruction="""You are an expert chef and dietary assistant.
Generate a meal plan with recipes tailored to the user's preferences, pantry items, and dietary constraints.
Use your MCP tools (get_recipe_suggestions, parse_pantry_items) to find matching recipes.
Return the output using the MealPlan schema. Don't omit instructions or notes.""",
    output_schema=MealPlan,
    tools=[mcp_toolset],
)

shopping_list_agent = LlmAgent(
    name="shopping_list_agent",
    model=gemini_model,
    instruction="""You are a shopping assistant.
Generate a consolidated shopping list and estimate the cost for the given meal plan.
Use your MCP tools (check_allergen_risk) to flag potential allergen items.
Return the output using the ShoppingList schema.""",
    output_schema=ShoppingList,
    tools=[mcp_toolset],
)

# -----------------------------------------------------------------------------
# Orchestrator Agent
# -----------------------------------------------------------------------------
orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=gemini_model,
    instruction="""You are the main coordinator of the NutriChef concierge.
You delegate work to the meal_planner_agent and shopping_list_agent.
Coordinate with them to fulfill the user's dietary requests.
When the user asks for a meal plan, call the meal_planner_agent.
When compiling the shopping list, call the shopping_list_agent.
Make sure you call the correct tool for the job. Do not invent details; ask the specialist agents.""",
    tools=[AgentTool(meal_planner_agent), AgentTool(shopping_list_agent)],
)

# -----------------------------------------------------------------------------
# Workflow Function Nodes
# -----------------------------------------------------------------------------
def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Analyze input for security (PII, prompt injection, and food safety). Forward if clean."""
    import re
    import datetime
    import sys
    
    text = ""
    if node_input and node_input.parts:
        text = node_input.parts[0].text or ""
        
    audit_log = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "event": "security_checkpoint_evaluation",
        "input_length": len(text),
        "scrubbed_pii": False,
        "verdict": "APPROVED",
        "severity": "INFO",
        "details": "Input passed security filters."
    }
    
    # 1. PII Scrubbing (Phone, Email, Medical/SSN numbers)
    email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    phone_pattern = re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b')
    ssn_pattern = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
    
    scrubbed_text = text
    if email_pattern.search(scrubbed_text):
        scrubbed_text = email_pattern.sub("[EMAIL_REDACTED]", scrubbed_text)
        audit_log["scrubbed_pii"] = True
    if phone_pattern.search(scrubbed_text):
        scrubbed_text = phone_pattern.sub("[PHONE_REDACTED]", scrubbed_text)
        audit_log["scrubbed_pii"] = True
    if ssn_pattern.search(scrubbed_text):
        scrubbed_text = ssn_pattern.sub("[SSN_REDACTED]", scrubbed_text)
        audit_log["scrubbed_pii"] = True
        
    if audit_log["scrubbed_pii"]:
        audit_log["severity"] = "WARNING"
        audit_log["details"] = "PII elements detected and redacted."
        
    # 2. Prompt Injection Detection
    injection_keywords = [
        "ignore previous instructions", 
        "system prompt", 
        "you are now", 
        "override", 
        "reveal instruction",
        "new instruction"
    ]
    has_injection = False
    for keyword in injection_keywords:
        if keyword in text.lower():
            has_injection = True
            break
            
    if has_injection:
        audit_log["verdict"] = "REJECTED"
        audit_log["severity"] = "CRITICAL"
        audit_log["details"] = "Prompt injection attempt detected."
        print(json.dumps(audit_log), file=sys.stderr)
        return Event(
            output="🚨 SECURITY ALERT: Prompt injection attempt detected. Access denied.",
            route="SECURITY_EVENT"
        )
        
    # 3. Domain-Specific Food Safety Check (Hazardous or Non-Food elements)
    non_food_hazards = ["poison", "bleach", "cyanide", "uranium", "arsenic", "strychnine", "toxic chemical"]
    has_hazard = False
    for hazard in non_food_hazards:
        if hazard in text.lower():
            has_hazard = True
            break
            
    if has_hazard:
        audit_log["verdict"] = "REJECTED"
        audit_log["severity"] = "CRITICAL"
        audit_log["details"] = "Hazardous non-food item requested."
        print(json.dumps(audit_log), file=sys.stderr)
        return Event(
            output="🚨 SECURITY ALERT: Request contains hazardous or non-food items. Access denied.",
            route="SECURITY_EVENT"
        )
        
    # Standard log print
    print(json.dumps(audit_log), file=sys.stderr)
    return Event(output=scrubbed_text, route="clean")

async def human_review(ctx: Context, node_input: Any):
    """Human-in-the-loop verification step for meal plans."""
    # Convert node_input to string safely
    text_content = ""
    if hasattr(node_input, "parts") and node_input.parts:
        text_content = node_input.parts[0].text or ""
    elif isinstance(node_input, dict):
        text_content = json.dumps(node_input, indent=2)
    else:
        text_content = str(node_input)

    if not ctx.resume_inputs:
        yield Event(state={"draft_meal_plan": text_content})
        yield RequestInput(
            interrupt_id="approve_meal_plan",
            message="NutriChef has generated a draft meal plan for you. Would you like to approve it and generate the shopping list? (Please reply 'yes' or describe modifications)"
        )
        return

    user_response = ctx.resume_inputs.get("approve_meal_plan", "").strip()
    if user_response.lower() == "yes":
        yield Event(output=ctx.state.get("draft_meal_plan"), route="approved")
    else:
        yield Event(output=user_response, route="replan")

@node(rerun_on_resume=True)
async def shopping_list_generator(ctx: Context, node_input: Any):
    """Call the shopping list agent to generate items for the approved meal plan."""
    res = await ctx.run_node(shopping_list_agent, node_input=str(node_input))
    
    # Store shopping list details in state
    shop_content = ""
    if isinstance(res, dict):
        shop_content = json.dumps(res, indent=2)
    else:
        shop_content = str(res)
        
    yield Event(
        output={"meal_plan": node_input, "shopping_list": shop_content},
        route="done"
    )

def final_output(ctx: Context, node_input: Any):
    """Format and display final outputs (or security events) to the user."""
    if isinstance(node_input, dict) and "meal_plan" in node_input:
        meal = node_input["meal_plan"]
        shop = node_input["shopping_list"]
        
        md_text = f"## 🍳 Your Approved Meal Plan\n\n{meal}\n\n---\n\n## 🛒 Consolidated Shopping List\n\n{shop}\n"
        yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=md_text)]))
        yield Event(output=node_input)
    else:
        yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=str(node_input))]))
        yield Event(output=node_input)

# -----------------------------------------------------------------------------
# Workflow Definition
# -----------------------------------------------------------------------------
edges = [
    (START, security_checkpoint),
    (security_checkpoint, {"clean": orchestrator_agent, "SECURITY_EVENT": final_output}),
    (orchestrator_agent, human_review),
    (human_review, {"replan": orchestrator_agent, "approved": shopping_list_generator}),
    (shopping_list_generator, final_output)
]

root_agent = Workflow(
    name="nutrichef_workflow",
    edges=edges,
    description="Dietary concierge that plans meals and generates shopping lists.",
)

app = App(
    root_agent=root_agent,
    name="app",
)
