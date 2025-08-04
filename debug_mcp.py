import asyncio
import os
from agno.tools.mcp import MCPTools, StreamableHTTPClientParams
from agno.models.openai.like import OpenAILike
from textwrap import dedent
from agno.agent import Agent

print(f"Current path is {os.getcwd()}")
from access_token import load_keys

async def test_mcp_connection():
    """测试MCP连接"""
    # 加载环境变量
    load_keys()
    
    # 检查环境变量
    access_token = os.getenv("ALI_OPENAPI_ACCESS_TOKEN")
    api_key = os.getenv("DASHSCOPE_API_KEY")
    
    if not access_token:
        print("错误: 未找到 ALI_OPENAPI_ACCESS_TOKEN")
        return
        
    if not api_key:
        print("错误: 未找到 DASHSCOPE_API_KEY")
        return
    
    print(f"Access token loaded: {access_token[:10]}...")
    print(f"API key loaded: {api_key[:10]}...")
    
    # 测试单个MCP连接
    print("测试 ECS 基础服务连接...")
    ecs_server_params = StreamableHTTPClientParams(
        url="https://openapi-mcp.cn-hangzhou.aliyuncs.com/accounts/1099419160256021/custom/ecs_base/id/1HP5DTSlYbLjFAwL/mcp",
        headers={'Authorization': f'Bearer {access_token}'}
    )
    
    try:
        async with MCPTools(
            server_params=ecs_server_params,
            transport="streamable-http",
            timeout_seconds=30
        ) as mcp_tools:
            print("ECS 基础服务连接成功")
            
            # 测试获取工具列表
            # 注意：这里我们不直接调用内部方法，而是测试完整的Agent流程
            model = OpenAILike(
                id="qwen-plus",
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            
            agent = Agent(
                model=model,
                tools=[mcp_tools],
                instructions=dedent("""\
                    你是一个阿里云云计算专家，请根据用户的问题，使用MCP服务查询阿里云的云产品信息，给出详细的解释。
                    请使用中文回答。
                """),
                markdown=True,
                show_tool_calls=True
            )
            
            print("正在测试查询...")
            await agent.aprint_response("我在杭州有哪些ECS实例?", stream=True)
            
    except Exception as e:
        print(f"ECS 基础服务连接失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_connection())