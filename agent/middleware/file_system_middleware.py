from langsmith.sandbox import SandboxClient
from deepagents.backends.langsmith import LangSmithSandbox
from deepagents.middleware import FilesystemMiddleware


def file_system_middleware():
    client = SandboxClient()
    sandbox = client.create_sandbox(template_name="deepagents-deploy")
    backend = LangSmithSandbox(sandbox=sandbox)
    return FilesystemMiddleware(backend=backend)
