import asyncio
import os
from textwrap import dedent
from agno.tools.mcp import MCPTools, StreamableHTTPClientParams
from agno.models.openai.like import OpenAILike
from agno.agent import Agent, RunResponse
import json
import logging
from typing import Dict, List, Any, Optional

from utils import QWEN3

print(f"Current path is {os.getcwd()}")
from access_token import load_keys

class MCPManager:
    """
    统一管理多个MCP Server的类
    """

    def __init__(self):
        self.servers_config = {
            "ecs_base": {
                "name": "ecs_base",
                "url": "https://openapi-mcp.cn-hangzhou.aliyuncs.com/accounts/1099419160256021/custom/ecs_base/id/1HP5DTSlYbLjFAwL/mcp",
                "description": "ECS云服务器相关基础操作"
            },
            "ecs_agent": {
                "name": "ecs_agent",
                "url": "https://openapi-mcp.cn-hangzhou.aliyuncs.com/accounts/1099419160256021/custom/ecs_agent/id/tq3oPa8Q3xJuFv90/mcp",
                "description": "ECS云助手相关操作"
            }
            # 可以继续添加更多MCP Server
        }
        self.access_token = None
        self.mcp_tools_contexts = {}

    def load_access_token(self):
        """
        加载访问令牌
        """
        self.access_token = os.getenv("ALI_OPENAPI_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("ALI_OPENAPI_ACCESS_TOKEN 环境变量未设置")
        return self.access_token

    async def get_all_tools_from_servers(self) -> List[Dict[str, Any]]:
        """
        从所有配置的MCP Server获取工具列表
        """
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        # 禁用日志以避免错误
        logging.disable(logging.CRITICAL)

        all_tools_info = []

        for server_key, server_config in self.servers_config.items():
            try:
                print(f"正在获取 {server_config['name']} 的工具列表...")

                headers = {'Authorization': f'Bearer {self.access_token}'}

                async def get_tools_from_server():
                    async with streamablehttp_client(
                        url=server_config["url"],
                        headers=headers
                    ) as (read_stream, write_stream, _):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            return tools

                tools = await get_tools_from_server()

                # 为每个工具添加服务器信息
                for tool in tools.tools:
                    tool_info = {
                        "name": tool.name,
                        "description": tool.description,
                        "server_key": server_key,
                        "server_name": server_config["name"]
                    }
                    all_tools_info.append(tool_info)

                print(f"从 {server_config['name']} 获取到 {len(tools.tools)} 个工具")

            except Exception as e:
                print(f"从 {server_config['name']} 获取工具列表失败: {e}")
                continue

        print(f"总共获取到 {len(all_tools_info)} 个工具")
        return all_tools_info

    def select_relevant_tools(self, all_tools_info: List[Dict[str, Any]], user_question: str, llm_api_key: str) -> Dict[str, List[str]]:
        """
        使用AI从所有工具中筛选出与用户问题相关的工具，并按服务器分组
        """
        # 创建AI代理
        simple_agent = Agent(
            model=OpenAILike(
                id=QWEN3,  # 使用更稳定的模型
                api_key=llm_api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            system_message="你是一个云计算专家，严格按照客户提供的上下文信息回答问题。"
        )

        # 准备工具信息（只传递必要信息给AI）
        brief_tools_info = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "server": tool["server_name"]
            }
            for tool in all_tools_info
        ]

        # 构造提示词
        prompt = (
            f"请根据提供的工具信息以及用户请求，选出最有可能需要调用的API列表，以JSON格式返回，不要包含其他信息。"
            f"返回格式为一个对象，键为服务器标识，值为该服务器上需要调用的工具名称数组。"
            f"工具信息如下：{json.dumps(brief_tools_info, ensure_ascii=False)}"
            f"用户提问：{user_question}"
        )

        try:
            response: RunResponse = simple_agent.run(prompt)
            print(f"AI筛选结果: {response.content}")

            selected_tools = json.loads(response.content)
            return selected_tools
        except Exception as e:
            print(f"AI筛选工具失败: {e}")
            # 备选方案：返回所有工具
            result = {}
            for tool in all_tools_info:
                server_key = tool["server_key"]
                if server_key not in result:
                    result[server_key] = []
                result[server_key].append(tool["name"])
            return result

    async def create_mcp_tools_with_selection(self, selected_tools: Dict[str, List[str]]) -> List[Any]:
        """
        根据筛选结果创建MCPTools实例
        使用上下文管理器确保正确初始化
        """
        mcp_tools_contexts = []
        mcp_tools_list = []
        for server_key, tool_names in selected_tools.items():
            if server_key not in self.servers_config:
                continue

            server_config = self.servers_config[server_key]
            try:
                print(f"初始化 {server_config['name']} 的MCP工具...")

                server_params = StreamableHTTPClientParams(
                    url=server_config["url"],
                    headers={'Authorization': f'Bearer {self.access_token}'}
                )

                # 使用上下文管理器创建MCP工具实例
                mcp_context = MCPTools(
                    server_params=server_params,
                    transport="streamable-http",
                    timeout_seconds=60,
                    include_tools=tool_names
                )

                # 保存上下文管理器以便后续使用
                mcp_tools_contexts.append(mcp_context)

                # 进入上下文并初始化工具
                mcp_tools = await mcp_context.__aenter__()
                await mcp_tools.initialize()
                mcp_tools_list.append(mcp_tools)

                print(f"{server_config['name']} 初始化成功，包含 {len(tool_names)} 个工具")

            except Exception as e:
                print(f"初始化 {server_config['name']} 失败: {e}")
                continue

        # 将上下文管理器保存到实例变量中，以便后续清理
        self.mcp_tools_contexts = mcp_tools_contexts
        return mcp_tools_list

    async def cleanup_mcp_tools(self):
        """
        清理MCP工具资源
        """
        for context in self.mcp_tools_contexts:
            try:
                await context.__aexit__(None, None, None)
            except:
                pass


async def chat_loop_with_multi_server_management() -> None:
    """
    多轮对话交互模式
    """
    manager = None
    agent = None

    try:
        # 创建MCP管理器
        manager = MCPManager()

        # 加载访问令牌
        manager.load_access_token()

        # 获取所有工具
        print("正在获取所有MCP Server的工具列表...")
        all_tools = await manager.get_all_tools_from_servers()

        if not all_tools:
            raise ValueError("未能从任何MCP Server获取到工具")

        # 获取LLM API密钥
        llm_api_key = os.getenv("DASHSCOPE_API_KEY")
        if not llm_api_key:
            raise ValueError("DASHSCOPE_API_KEY 环境变量未设置")

        # 筛选相关工具（初始时可以使用一个通用问题来获取所有可能需要的工具）
        print("正在筛选相关工具...")
        selected_tools = manager.select_relevant_tools(all_tools, "ECS相关操作", llm_api_key)
        print(f"筛选结果: {selected_tools}")

        # 创建MCP工具实例
        print("正在创建MCP工具实例...")
        mcp_tools_list = await manager.create_mcp_tools_with_selection(selected_tools)

        if not mcp_tools_list:
            raise ValueError("未能创建任何MCP工具实例")

        # 创建Agent
        model = OpenAILike(
            id=QWEN3,
            api_key=llm_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

        # 构建服务器描述信息
        server_descriptions = "\n".join([
            f"- {key}: {config['description']}"
            for key, config in manager.servers_config.items()
        ])

        agent = Agent(
            model=model,
            tools=mcp_tools_list,
            instructions=dedent(f"""\
                你是一个阿里云云计算运维专家，请根据用户的问题，使用适当的MCP服务, 帮助用户解决运维方面的实际问题。
                请使用中文回答。

                可用的服务包括：
                {server_descriptions}

                请根据用户问题的上下文选择合适的服务进行查询, 每次都选择最恰当的服务。
                执行完每个服务后, 输出必要的结果信息。
            """),
            markdown=True,
            show_tool_calls=True
        )

        print("\n" + "="*50)
        print("欢迎使用阿里云MCP多服务智能助手！")
        print("="*50)
        print("您可以询问关于ECS云服务器的各种问题，例如：")
        print("- 我在杭州有哪些ECS实例?")
        print("- 查询我的ECS实例详情")
        print("- ECS云助手相关操作")
        print("- 输入 'quit'、'exit' 或 '退出' 结束对话")
        print("-" * 50)

        # 多轮对话循环
        while True:
            try:
                # 获取用户输入
                user_input = input("\n请输入您的问题: ").strip()

                # 检查退出命令
                if user_input.lower() in ['quit', 'exit', '退出', 'q']:
                    print("感谢使用，再见！")
                    break

                # 跳过空输入
                if not user_input:
                    print("请输入有效问题")
                    continue

                print("\n正在处理您的问题...")
                # 运行Agent并获取响应（保持上下文）
                await agent.aprint_response(user_input, stream=True)

            except KeyboardInterrupt:
                print("\n\n对话被用户中断，再见！")
                break
            except EOFError:
                print("\n\n输入结束，再见！")
                break
            except Exception as e:
                print(f"处理问题时出错: {e}")
                print("请重试或输入 'quit' 退出")
                continue

    except Exception as e:
        print(f"初始化Agent时出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理资源
        if manager:
            await manager.cleanup_mcp_tools()


async def run_agent_with_multi_server_management(user_question: str) -> None:
    """
    使用多Server管理器运行Agent（单次问答模式）
    """
    manager = None
    try:
        # 创建MCP管理器
        manager = MCPManager()

        # 加载访问令牌
        manager.load_access_token()

        # 获取所有工具
        print("正在获取所有MCP Server的工具列表...")
        all_tools = await manager.get_all_tools_from_servers()

        if not all_tools:
            raise ValueError("未能从任何MCP Server获取到工具")

        # 获取LLM API密钥
        llm_api_key = os.getenv("DASHSCOPE_API_KEY")
        if not llm_api_key:
            raise ValueError("DASHSCOPE_API_KEY 环境变量未设置")

        # 筛选相关工具
        print("正在筛选相关工具...")
        selected_tools = manager.select_relevant_tools(all_tools, user_question, llm_api_key)
        print(f"筛选结果: {selected_tools}")

        # 创建MCP工具实例
        print("正在创建MCP工具实例...")
        mcp_tools_list = await manager.create_mcp_tools_with_selection(selected_tools)

        if not mcp_tools_list:
            raise ValueError("未能创建任何MCP工具实例")

        # 创建Agent
        model = OpenAILike(
            id=QWEN3,
            api_key=llm_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

        # 构建服务器描述信息
        server_descriptions = "\n".join([
            f"- {key}: {config['description']}"
            for key, config in manager.servers_config.items()
        ])

        agent = Agent(
            model=model,
            tools=mcp_tools_list,
            instructions=dedent(f"""\
                你是一个阿里云云计算专家，请根据用户的问题，使用适当的MCP服务查询阿里云的云产品信息，给出详细的解释。
                请使用中文回答。

                可用的服务包括：
                {server_descriptions}

                请根据用户问题的上下文选择合适的服务进行查询。
            """),
            markdown=True,
            show_tool_calls=True
        )

        # 运行Agent
        print("正在运行Agent...")
        await agent.aprint_response(user_question, stream=True)

    except Exception as e:
        print(f"运行Agent时出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理资源
        if manager:
            await manager.cleanup_mcp_tools()

# Example usage
if __name__ == "__main__":
    # 加载环境变量
    print("Loading environment variables...")
    load_keys()

    # 检查命令行参数以决定运行模式
    # python multi_mcp.py --chat
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--chat":
        # 多轮对话模式
        print("启动多轮对话模式...")
        asyncio.run(chat_loop_with_multi_server_management())
    else:
        # 单次问答模式
        user_question = "我在杭州有哪些ECS实例?"
        print(f"运行单次问答模式，问题: {user_question}")
        asyncio.run(run_agent_with_multi_server_management(user_question))
