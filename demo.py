import asyncio
import os
from textwrap import dedent
from agno.tools.mcp import MCPTools, StreamableHTTPClientParams
from agno.models.openai.like import OpenAILike
# from mcp.client.streamable_http import streamablehttp_client
# from mcp import ClientSession
import asyncio
from agno.agent import Agent, RunResponse
import json
# Important: Just to avoid such logging error like "JSONRPCError.jsonrpc Field required ...
import logging
# logging.basicConfig(level=logging.DEBUG)
print(f"Current path is {os.getcwd()}")
from access_token import load_keys
# load_keys()

def get_selected_tools_list(server_url, hearders, llm_api_key, user_question):
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession
    import asyncio
    from agno.agent import Agent, RunResponse
    from agno.models.openai.like import OpenAILike
    import json
    # Important: Just to avoid such logging error like "JSONRPCError.jsonrpc Field required ...
    import logging
    logging.disable(logging.CRITICAL)
    # 1. Get all tools via tools/list
    all_tools = None
    async def get_all_tools():
        # Connect to a streamable HTTP server
        async with streamablehttp_client(url=server_url,headers=hearders)as(read_stream, write_stream,_):
            # Create a session using the client streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                all_tools = await session.list_tools()
                print(f"Number of tools: {len(all_tools.tools)}")
                return all_tools
    all_tools = asyncio.run(get_all_tools())
    # 2. Collect all tools brief info
    brife_tools_info = [
        {
            "name": tool.name,
            "description": tool.description,
        }
        for tool in all_tools.tools]
    # 3. Create an agent
    simple_agent = Agent(
        model=OpenAILike(
            id="qwen-max",
            api_key=llm_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        system_message="""
            你是一个云计算专家，严格按照请客户提供的上下文信息回答问题。
            """,
        )

    # 4. Run the agent to tell us which tools are needed for user questio
    prompt = (
        f"请根据提供的工具信息以及用户请求，你需要给出可能需要调用的api列表，以Json形式返回，要精简、不需要其他信息。格式上，返回值不带```、json等字符串，"
        f"工具信息如下：{json.dumps(brife_tools_info)},"
        f"现在客户提问：{user_question}"
    )
    response: RunResponse = simple_agent.run(prompt)
    print(response.content)
    tool_to_use_list = json.loads(response.content)
    print(f"Selected Tool List: {tool_to_use_list}")
    return tool_to_use_list


async def run_agent_multi_mcp(message) -> None:

    ecs_server_params = StreamableHTTPClientParams(
        url = "https://openapi-mcp.cn-hangzhou.aliyuncs.com/accounts/1099419160256021/custom/ecs_base/id/1HP5DTSlYbLjFAwL/mcp",
        headers = {'Authorization': f'Bearer {os.getenv("ALI_OPENAPI_ACCESS_TOKEN")}'}
    )
    ecs_agent_server_params = StreamableHTTPClientParams(
        url = "https://openapi-mcp.cn-hangzhou.aliyuncs.com/accounts/1099419160256021/custom/ecs_agent/id/tq3oPa8Q3xJuFv90/mcp",
        headers = {'Authorization': f'Bearer {os.getenv("ALI_OPENAPI_ACCESS_TOKEN")}'}
    )


    async with MCPTools(server_params=ecs_server_params, transport="streamable-http", timeout_seconds=30 ) as ecs, \
        MCPTools(server_params=ecs_agent_server_params, transport="streamable-http", timeout_seconds=30 ) as ecs_agent:
        # Initialize the model
        model=OpenAILike(id="qwen-max",
                         api_key=os.getenv("DASHSCOPE_API_KEY"),
                         base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        # Initialize the agent
        agent = Agent(model=model,
                      tools=[ecs, ecs_agent],
                      instructions=dedent("""\
                          你是一个阿里云云计算专家，请根据用户的问题，使用MCP服务查询阿里云的云产品信息，给出详细的解释。
                          请使用中文回答
                          每轮回复中, 只调用最相关的 MCP 工具
                      """),
                      markdown=True,
                      show_tool_calls=True)

        # Initialize the model

    # Run the agent
    await agent.aprint_response(message, stream=True)


async def run_agent(config):

    # Setup agent with MCP tools
    server_params = StreamableHTTPClientParams(url=config["server_url"], headers=config["headers"])
    async with MCPTools(server_params=server_params,
                        transport="streamable-http",
                        timeout_seconds=30,
                        include_tools=config["tool_to_use_list"]) as mcp_tools:
        # Initialize the model
        model=OpenAILike(id="qwen-max",
                         api_key=config["llm_api_key"],
                         base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

        # Initialize the agent
        agent = Agent(model=model,
                      tools=[mcp_tools],
                      instructions=dedent("""\
                          你是一个阿里云云计算专家，请根据用户的问题，使用MCP服务查询阿里云的云产品信息，给出详细的解释。
                          请使用中文回答
                      """),
                      markdown=True,
                      show_tool_calls=True)

        # Run the agent
        await agent.aprint_response(config["user_question"], stream=True)


# Example usage
if __name__ == "__main__":
    # 加载环境变量
    print("Loading environment variables...")
    load_keys()

    # 1. User question goes here
    user_question = "我在杭州有哪些ECS实例?"

    # 2. Prepare arguments for the agent
    url = "https://openapi-mcp.cn-hangzhou.aliyuncs.com/accounts/1099419160256021/custom/ecs_base/id/1HP5DTSlYbLjFAwL/mcp"     # Full ECS List
    headers = {'Authorization': f'Bearer {os.getenv("ALI_OPENAPI_ACCESS_TOKEN")}'}
    llm_api_key = os.getenv("DASHSCOPE_API_KEY")

    # 3. Get selected tools list by user question
    seleted_tools = get_selected_tools_list(url, headers, llm_api_key, user_question)
    # print(seleted_tools)

    # # 4. Setup config
    config = {
        "server_url": url,
        "llm_api_key": llm_api_key,
        "headers": headers,
        "user_question": user_question,
        "tool_to_use_list": seleted_tools
    }

    # 5. Query LLM
    asyncio.run(run_agent(config))