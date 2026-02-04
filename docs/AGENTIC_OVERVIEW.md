# Agentic Overview & Automation

## 1. Project Objectives
The goal is to integrate an autonomous AI agent into the **Ansible SimpleWeb** cluster. This agent will act as an intelligent operator, monitoring the system, reviewing outputs, and assisting with playbook development.

### Core Responsibilities
1.  **Log Review & Verification**: Analyze execution logs to verify expected states and identify anomalies that standard exit codes might miss.
2.  **Playbook Assistant**: Generate and review playbooks based on user instructions, offering enhancement suggestions and security improvements.
3.  **System Monitoring**: Validate that scheduled jobs ran successfully and monitor the overall health of the cluster.
4.  **Insight Generation**: Review configuration outputs (e.g., RouterOS configs, server facts) to flag security risks, update needs, or resource constraints.
5.  **Continuous Improvement**: Maintain a prioritized list of suggested enhancements for the codebase.

## 2. Architecture

### New Component: `agent-service`
A new containerized service will be added to the Docker Compose stack.

*   **Runtime**: Python-based service.
*   **Access**:
    *   **API**: Communicates with `ansible-web` via REST API.
    *   **Storage**: Read-only access to `logs/` and `playbooks/` volumes.
    *   **Model**: Access to a local LLM inference endpoint.

### LLM & RAG Strategy
*   **Model Selection**: We recommend **Qwen2.5-Coder-7B-Instruct** or **Llama-3-8B-Instruct**. These models offer a strong balance of coding capability, reasoning, and efficiency for local deployment.
*   **Inference**:
    *   *Option A (Preferred)*: Use a dedicated inference container (e.g., `ollama` or `vllm`) providing an OpenAI-compatible API.
    *   *Option B (Minimal)*: Use `llama-cli` directly within the agent container if resources are highly constrained.
*   **RAG (Retrieval-Augmented Generation)**:
    *   The agent will maintain a vector index of:
        *   Existing Playbooks
        *   Documentation (`docs/*.md`)
        *   System Context (`memory.md`)
    *   This allows the agent to write code that adheres to project conventions and understands the specific environment.

## 3. Phased Implementation Plan

We will adopt a phased approach to ensure stability.

### Phase 1: Foundation & Infrastructure
*   [ ] Create `agent-service` container in `docker-compose.yml`.
*   [ ] Set up the LLM inference backend (e.g., add `ollama` service or configure `llama-cli`).
*   [ ] Implement basic `AgentClient` to communicate with the Ansible SimpleWeb API.
*   [ ] Establish the RAG pipeline (ingesting `docs/` and `playbooks/`).

### Phase 2: Log Reviewer (Passive)
*   [ ] Implement a log monitoring loop.
*   [ ] Create prompts for analyzing Ansible logs for "soft failures" or warnings.
*   [ ] Enable the agent to post "Review Notes" (initially just logging them to a file or console).

### Phase 3: Playbook Assistant (Active)
*   [ ] Create an interface (CLI or API endpoint) to request playbook generation.
*   [ ] Implement the "Proposal" workflow: Agent generates YAML -> Admin reviews -> Deploy.
*   [ ] Implement "Enhancement Suggestions": Agent scans existing playbooks and suggests improvements.

### Phase 4: System Monitor & Insights
*   [ ] Implement schedule validation (did the cron job actually run?).
*   [ ] Implement specific analyzers for RouterOS and Server Configs (e.g., "check for default passwords" using LLM reasoning on config dumps).

## 4. Operational Guidelines
*   **Human-in-the-loop**: All agent-generated code must be approved before execution.
*   **Fallback**: The system must remain fully functional if the agent service is down.
*   **Safety**: The agent is read-only on production infrastructure unless executing a specific, approved change workflow.
