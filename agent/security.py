import os
import yaml
import logging

logger = logging.getLogger(__name__)

class SecurityEnforcer:
    def __init__(self, policy_path='agent/security_policy.yaml'):
        self.policy_path = policy_path
        self.policy = self._load_policy()
        
    def _load_policy(self):
        try:
            if os.path.exists(self.policy_path):
                with open(self.policy_path, 'r') as f:
                    return yaml.safe_load(f)
            else:
                logger.warning(f"Security policy not found at {self.policy_path}, using defaults.")
                return {}
        except Exception as e:
            logger.error(f"Error loading security policy: {e}")
            return {}

    def reload_policy(self):
        self.policy = self._load_policy()
        logger.info("Security policy reloaded")

    def check_playbook_generation(self, user_request):
        """
        Check if a playbook generation request is allowed.
        Returns (bool, str) -> (allowed, reason)
        """
        feature_policy = self.policy.get('policy', {}).get('features', {}).get('playbook_generation', {})
        strict_mode = feature_policy.get('strict_mode', True)
        allowed_verbs = feature_policy.get('allowed_verbs', [])
        restricted_verbs = feature_policy.get('restricted_verbs', [])
        
        request_lower = user_request.lower()
        
        # 1. Check Restricted Verbs (High Priority Block)
        for verb in restricted_verbs:
            if verb in request_lower:
                return False, f"Request contains restricted action: '{verb}'"
        
        # 2. Check Allowed Verbs (If Strict Mode)
        if strict_mode:
            has_allowed_verb = False
            for verb in allowed_verbs:
                if verb in request_lower:
                    has_allowed_verb = True
                    break
            
            if not has_allowed_verb:
                return False, "Request does not contain any permitted actions."
                
        return True, "Allowed"
