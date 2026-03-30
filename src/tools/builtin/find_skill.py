"""Find Skills 工具 - 用于在遇到无法解决的问题时查找相关 skills"""

import os
import subprocess
from typing import List, Dict, Any

from hello_agents.tools import Tool, ToolParameter, ToolResponse, tool_action


class FindSkillTool(Tool):
    """Find Skills 工具

    当遇到无法解决的问题时，使用此工具搜索和安装相关的 skills。
    支持从多个 registry 搜索：skills.sh, AgentSkill.work, ClawHub
    """

    def __init__(self, workspace_path: str = None):
        super().__init__(
            name="find_skill",
            description="""查找和安装 agent skills。

用法：
1. search: 搜索 skills - 输入关键词，返回匹配的 skill 包名
2. install: 安装 skill - 输入包名（如 vercel-labs/agent-skills），自动克隆到本地 skills 目录

示例：
- find_skill.search(query="git") 搜索 git 相关 skills
- find_skill.install(package="vercel-labs/agent-skills") 安装 skills 到本地""",
            expandable=True,
        )
        self.workspace_path = workspace_path or "~/.helloclaw/workspace"

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        """执行 skills 查找或安装"""
        action = parameters.get("action", "")
        query = parameters.get("query", "")
        package = parameters.get("package", "")

        # 如果有 package 参数，执行安装
        if package:
            result = self._install_skill(package, self.workspace_path)
            return ToolResponse.success(text=result)

        # 否则执行搜索
        if query:
            return self._find_skills(query)

        return ToolResponse.error(
            code="INVALID_INPUT", message="请提供 query（搜索）或 package（安装）参数"
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索关键词（如：git, web, ppt, database 等）",
                required=False,
            ),
            ToolParameter(
                name="package",
                type="string",
                description="要安装的 skill 包名（如：vercel-labs/agent-skills, anthropics/skills@pptx）",
                required=False,
            ),
            ToolParameter(
                name="action",
                type="string",
                description="操作类型：search 或 install",
                required=False,
            ),
        ]

    def _find_skills(self, query: str) -> ToolResponse:
        """搜索 skills

        Args:
            query: 搜索关键词

        Returns:
            ToolResponse: 搜索结果
        """
        if not query:
            return ToolResponse.error(
                code="INVALID_INPUT", message="搜索关键词不能为空"
            )

        try:
            cmd = "npx.cmd -y skills find " + query
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                shell=True,
            )

            if result.returncode == 0:
                output = result.stdout or ""
                if not output.strip():
                    output = f"未找到与 '{query}' 相关的 skills。可以尝试其他关键词或访问 https://skills.sh 浏览更多 skills。"
                else:
                    # 清理 ANSI 转义序列和尖括号内容
                    import re

                    clean_output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
                    # 移除尖括号中的示例文本（如 <owner/repo@skill>）
                    clean_output = re.sub(r"<[^>]+>", "", clean_output)

                    # 提取包名 - 匹配格式: anthropics/skills@frontend-design
                    packages = re.findall(
                        r"([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+@[\w-]+)", clean_output
                    )

                    if packages:
                        # 自动安装第一个最流行的 skill
                        first_package = packages[0]
                        install_result = self._install_skill(
                            first_package, self.workspace_path
                        )
                        output = f"✅ 已自动安装: {first_package}\n\n{install_result}\n\n原始搜索结果：\n{output}"
                    else:
                        output += f'\n\n如需安装，请使用 find_skill.install(package="<包名>") 命令。\n例如：find_skill.install(package="anthropics/skills@frontend-design")'

                return ToolResponse.success(
                    text=output,
                    data={"query": query},
                )
            else:
                return ToolResponse.error(
                    code="FIND_SKILL_ERROR", message=f"搜索失败: {result.stderr}"
                )

        except subprocess.TimeoutExpired:
            return ToolResponse.error(code="TIMEOUT", message="搜索超时，请重试")
        except FileNotFoundError:
            return ToolResponse.error(
                code="NOT_FOUND", message="未找到 npx，请确保已安装 Node.js"
            )
        except Exception as e:
            return ToolResponse.error(
                code="FIND_SKILL_ERROR", message=f"搜索失败: {str(e)}"
            )

    @tool_action("search", "搜索 skills")
    def _search_action(self, query: str) -> str:
        """搜索 skills

        Args:
            query: 搜索关键词
        """
        response = self._find_skills(query)
        return response.text

    @tool_action("install", "安装 skill")
    def _install_action(self, package: str) -> str:
        """安装 skill

        Args:
            package: skill 包名（如：vercel-labs/agent-skills）
        """
        return self._install_skill(package, self.workspace_path)

    def _install_skill(self, package: str, workspace_path: str = None) -> str:
        """安装 skill - 使用 git clone 方式

        Args:
            package: skill 包名 (格式: owner/repo 或 owner/repo@skill)
            workspace_path: 工作空间路径，用于确定 skills 目录位置

        Returns:
            安装结果
        """
        if not package:
            return "错误：包名不能为空"

        import shutil

        try:
            workspace = os.path.expanduser(workspace_path or "~/.helloclaw/workspace")
            skills_dir = os.path.join(workspace, "skills")
            os.makedirs(skills_dir, exist_ok=True)

            # 解析 package: owner/repo@skill -> repo, skill
            if "@" in package:
                parts = package.split("@")
                repo_url = f"https://github.com/{parts[0]}.git"
                skill_name = parts[1]
            else:
                repo_url = f"https://github.com/{package}.git"
                skill_name = package.split("/")[-1]

            # 使用 git clone
            temp_dir = os.path.join(workspace, f".temp_skill_{id(package)}")
            clone_dir = os.path.join(temp_dir, skill_name)

            # 清理旧目录
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

            # 执行 clone
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, clone_dir],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )

            if result.returncode != 0:
                return f"安装失败: {result.stderr or 'Git clone 失败'}\n\n可能是私有仓库或网络问题"

            # 查找 skills 目录结构
            skills_to_install = []

            # 检查是否有 skills/ 子目录
            repo_skills_dir = os.path.join(clone_dir, "skills")
            if os.path.exists(repo_skills_dir) and os.path.isdir(repo_skills_dir):
                # 多个 skills
                for item in os.listdir(repo_skills_dir):
                    item_path = os.path.join(repo_skills_dir, item)
                    if os.path.isdir(item_path) and os.path.isfile(
                        os.path.join(item_path, "SKILL.md")
                    ):
                        skills_to_install.append((item, item_path))
            elif os.path.isfile(os.path.join(clone_dir, "SKILL.md")):
                # 整个仓库就是一个 skill
                skills_to_install.append((skill_name, clone_dir))
            else:
                # 查找任何包含 SKILL.md 的目录
                for root, dirs, files in os.walk(clone_dir):
                    if "SKILL.md" in files:
                        name = os.path.basename(root)
                        skills_to_install.append((name, root))
                        break

            if not skills_to_install:
                return f"安装失败: 未在仓库中找到 SKILL.md"

            # 安装每个 skill
            installed = []
            for name, src_dir in skills_to_install:
                target_dir = os.path.join(skills_dir, name)
                try:
                    if os.path.exists(target_dir):
                        shutil.rmtree(target_dir, ignore_errors=True)
                    shutil.copytree(src_dir, target_dir)
                    installed.append(name)
                except Exception as e:
                    pass

            # 清理临时目录
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

            if installed:
                return f'成功安装 {len(installed)} 个 skills: {", ".join(installed)}\n安装目录: {skills_dir}\n\n使用 Skill 工具加载: Skill(skill="<skill名称>")'
            else:
                return "安装失败: 无法复制文件"

        except subprocess.TimeoutExpired:
            return "安装超时，请重试"
        except Exception as e:
            return f"安装失败: {str(e)}"
