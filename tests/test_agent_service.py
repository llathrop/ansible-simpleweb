import unittest
import json
import os
import shutil
import tempfile
import yaml
from unittest.mock import patch, MagicMock

# Import the service logic directly
from agent import service
from agent.llm_client import LLMClient

class TestAgentService(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for reviews
        self.test_dir = tempfile.mkdtemp()
        self.original_reviews_dir = service.REVIEWS_DIR
        self.original_logs_dir = service.LOGS_DIR
        
        service.REVIEWS_DIR = os.path.join(self.test_dir, 'reviews')
        service.LOGS_DIR = os.path.join(self.test_dir, 'logs')
        
        os.makedirs(service.REVIEWS_DIR, exist_ok=True)
        os.makedirs(service.LOGS_DIR, exist_ok=True)
        
        self.app = service.app.test_client()
        self.app.testing = True

    def tearDown(self):
        # Cleanup
        shutil.rmtree(self.test_dir)
        service.REVIEWS_DIR = self.original_reviews_dir
        service.LOGS_DIR = self.original_logs_dir

    def test_health_check(self):
        """Phase 1: Verify health endpoint returns correct structure."""
        response = self.app.get('/health')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'online')
        self.assertEqual(data['service'], 'agent-service')

    @patch('agent.service.threading.Thread')
    def test_trigger_log_review(self, mock_thread):
        """Phase 2: Verify log review trigger accepts request and starts background task."""
        payload = {
            'job_id': '12345',
            'exit_code': 0
        }
        response = self.app.post('/trigger/log-review', 
                                 data=json.dumps(payload),
                                 content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['job_id'], '12345')
        self.assertEqual(data['status'], 'accepted')
        
        # Verify thread was started with correct args
        mock_thread.assert_called_once()
        args = mock_thread.call_args[1]['args']
        self.assertEqual(args[0], '12345')
        self.assertEqual(args[1], 0)

    def test_get_review_missing(self):
        """Phase 2: Verify 404 for missing review."""
        response = self.app.get('/reviews/missing-job')
        self.assertEqual(response.status_code, 404)

    def test_get_review_existing(self):
        """Phase 2: Verify retrieval of existing review."""
        job_id = 'test-job-1'
        review_data = {
            'job_id': job_id,
            'review': {'summary': 'Test Summary'}
        }
        
        with open(os.path.join(service.REVIEWS_DIR, f"{job_id}.json"), 'w') as f:
            json.dump(review_data, f)
            
        response = self.app.get(f"/reviews/{job_id}")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['job_id'], job_id)
        self.assertEqual(data['review']['summary'], 'Test Summary')

    @patch('agent.service.requests.get')
    @patch('agent.service.llm_client')
    def test_process_log_review_logic(self, mock_llm, mock_get):
        """Phase 2: Verify the logic of processing a review (Integration-like unit test)."""
        job_id = 'job-123'
        playbook = 'test.yml'
        log_content = "PLAY [test] ... OK"
        
        # Mock Ansible Web API response
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'job_id': job_id,
            'playbook': playbook,
            'log_file': 'job-123.log'
        }
        
        # Create dummy log file
        with open(os.path.join(service.LOGS_DIR, 'job-123.log'), 'w') as f:
            f.write(log_content)
            
        # Mock LLM analysis
        mock_review_result = {
            "summary": "Success",
            "issues": []
        }
        mock_llm.analyze_log.return_value = mock_review_result
        
        # Execute the processing function directly
        service.process_log_review(job_id, 0)
        
        # Verify LLM was called correctly
        mock_llm.analyze_log.assert_called_with(job_id, playbook, 0, log_content)
        
        # Verify review file was created
        review_path = os.path.join(service.REVIEWS_DIR, f"{job_id}.json")
        self.assertTrue(os.path.exists(review_path))
        
        with open(review_path, 'r') as f:
            saved_data = json.load(f)
            self.assertEqual(saved_data['review'], mock_review_result)

    @patch('agent.service.rag_engine')
    @patch('agent.service.llm_client')
    def test_generate_playbook(self, mock_llm, mock_rag):
        """Phase 3: Verify playbook generation flow."""
        # Mock RAG
        mock_rag.query.return_value = ["- name: existing playbook task"]
        
        # Mock LLM
        mock_llm.generate_playbook.return_value = "```yaml\n- hosts: all\n  tasks: ...\n```"
        
        payload = {'request': 'Install nginx'}
        response = self.app.post('/agent/generate',
                                 data=json.dumps(payload),
                                 content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        self.assertIn('generated_playbook', data)
        self.assertTrue(data['context_used'])
        
        # Verify calls
        mock_rag.query.assert_called_with('Install nginx', n_results=3)
        mock_llm.generate_playbook.assert_called()

    @patch('agent.service.rag_engine')
    def test_rag_ingest(self, mock_rag):
        """Phase 3: Verify ingest trigger."""
        response = self.app.post('/rag/ingest')
        self.assertEqual(response.status_code, 200)
        mock_rag.ingest_data.assert_called()

    def test_generate_playbook_guardrails(self):
        """Phase 4: Verify destructive requests are blocked and allowed requests pass (Allowlist)."""
        # Test Restricted (should be blocked)
        destructive_requests = [
            "delete all logs",
            "remove the database",
            "rm -rf /",
            "drop table users"
        ]
        
        for req in destructive_requests:
            payload = {'request': req}
            response = self.app.post('/agent/generate',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            self.assertEqual(response.status_code, 403, f"Failed to block restricted: {req}")
            data = json.loads(response.data)
            self.assertIn('Request blocked', data['error'])

        # Test Allowed (should pass)
        # We need to mock RAG and LLM again since these will now proceed
        with patch('agent.service.rag_engine') as mock_rag, \
             patch('agent.service.llm_client') as mock_llm:
            
            mock_rag.query.return_value = []
            mock_llm.generate_playbook.return_value = "```yaml\n...```"

            allowed_requests = [
                "Install nginx",
                "Check server status",
                "Verify disk space"
            ]
            
            for req in allowed_requests:
                payload = {'request': req}
                response = self.app.post('/agent/generate',
                                         data=json.dumps(payload),
                                         content_type='application/json')
                
                self.assertEqual(response.status_code, 200, f"Failed to allow valid request: {req}")

        # Test Unknown/Disallowed (should be blocked if strict mode is on)
        # Assuming strict mode is on by default in policy
        unknown_requests = [
            "Do something random",
            "Make me a sandwich"
        ]
        
        for req in unknown_requests:
            payload = {'request': req}
            response = self.app.post('/agent/generate',
                                     data=json.dumps(payload),
                                     content_type='application/json')
            
            self.assertEqual(response.status_code, 403, f"Failed to block unknown request: {req}")


    def test_prompt_template_inheritance(self):
        """Phase 4: Verify that system_core is injected into other prompts."""
        # Create a temporary prompts file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump({
                'prompts': {
                    'system_core': 'CORE: Guardrails Active.',
                    'test_prompt': {
                        'system': '{{ system_core }}\nSpecific Instruction.'
                    }
                }
            }, tmp)
            tmp_path = tmp.name

        try:
            # Initialize client with this file
            client = LLMClient(prompts_path=tmp_path)
            
            # Access loaded prompts directly to verify injection
            loaded_prompts = client.prompts.get('prompts', {})
            test_system_prompt = loaded_prompts.get('test_prompt', {}).get('system')
            
            self.assertIn('CORE: Guardrails Active.', test_system_prompt)
            self.assertIn('Specific Instruction.', test_system_prompt)
            
        finally:
            os.remove(tmp_path)

if __name__ == '__main__':
    unittest.main()
