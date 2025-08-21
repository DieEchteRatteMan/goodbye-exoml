
import http.server
import socketserver
import os
import json
import urllib.request
import urllib.error
import io
import time
import datetime
import traceback
import threading
import math
import json
import secrets
import signal
import sys
import socket
import requests
import aiohttp
from aiohttp import web
import asyncio
from concurrent.futures import ThreadPoolExecutor
import queue
import gc
from collections import deque
from threading import RLock
import random

PORT = 24458
HOST = "0.0.0.0"
CONFIG_FILE = "providers.json"
USERS_CONFIG_FILE = "users.json"
ADMIN_API_KEY = "sj-jadsfioewjporpiqwepij"
AVAILABLE_MODELS_LIST = []
STATIC_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
MITIGATED_IPS_FILE = "mitigated_ips.json"

OPENSOURCE_MODELS = [
    "llama-3.3-nemotron-super-49b",
    "devstral-small-2505",
    "deepseek-v3-0324-selfhost",
    "kimi-k2-selfhost"
]
OPENSOURCE_SK_TEST_KEY = "sk-test"

providers_config = {"endpoints": {}}
users_config = {"users": {}}
user_config_lock = threading.Lock()
providers_config_lock = threading.Lock()
hackathon_key_rate_limiter = {}
hackathon_key_rate_limiter_lock = threading.Lock()

opensource_rpm_tracker = {}
opensource_rpm_tracker_lock = threading.Lock()

class RequestRateMonitor:
    def __init__(self):
        self.request_count = 0
        self.last_reset = time.time()
        self.attack_start_time = None
        self.attack_request_count = 0
        self.last_attack_log = 0
        self.attack_threshold = 200
        self.peak_rps = 0
        self.webhook_url = "https://discord.com/api/webhooks/1387853681445306388/GSp7DkuV2Df21MoADB-rcwhPQC9sKGENeQql5YZc2YGvZZ56o1KRrTCXSgTmGA09zYk8"
        
        self.whitelisted_ips = {
            "88.99.145.13",
            "37.114.39.160"
        }
        
        self.pending_notification = None
        self.notification_timer = None
        self.cooldown_duration = 60
        self.total_attack_stats = {
            'total_duration': 0.0,
            'total_requests': 0,
            'max_peak_rps': 0,
            'attack_count': 0
        }
        
        self.ip_blocking_timer = None
        self.pending_blocked_ips = []
        
        self.ip_requests = {}
        self.ip_last_reset = {}
        self.blocked_ips = {}
        self.single_ip_threshold = 20
        self.block_duration = 3600
        
        self.ip_patterns = {}
        self.malicious_threshold = 200
        self.pattern_window = 60
        
        self.mitigated_ips = set()
        self.mitigated_ips_lock = threading.Lock()
        self._load_mitigated_ips()
        
        self.pending_blocks = set()
        self.pending_blocks_lock = threading.Lock()
        self.batch_block_timer = None
        self.batch_block_interval = 10
        
        print(f"✅ IP WHITELIST: {len(self.whitelisted_ips)} IPs are whitelisted: {', '.join(self.whitelisted_ips)}")
        print(f"📋 MITIGATED IPS: {len(self.mitigated_ips)} IPs previously mitigated and tracked")
        print(f"⏱️ BATCH BLOCKING: IPs will be blocked in batches every {self.batch_block_interval} seconds")
        
    def _load_mitigated_ips(self):
        """Load previously mitigated IPs from file."""
        try:
            with open(MITIGATED_IPS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data.get('mitigated_ips'), list):
                    self.mitigated_ips = set(data['mitigated_ips'])
                    print(f"✅ Loaded {len(self.mitigated_ips)} previously mitigated IPs from {MITIGATED_IPS_FILE}")
                else:
                    self.mitigated_ips = set()
                    print(f"⚠️ Invalid format in {MITIGATED_IPS_FILE}, starting with empty mitigated IPs list")
        except FileNotFoundError:
            self.mitigated_ips = set()
            print(f"📋 No previous mitigated IPs file found, starting with empty list")
        except json.JSONDecodeError:
            self.mitigated_ips = set()
            print(f"❌ Invalid JSON in {MITIGATED_IPS_FILE}, starting with empty mitigated IPs list")
        except Exception as e:
            self.mitigated_ips = set()
            print(f"❌ Error loading mitigated IPs: {e}, starting with empty list")
    
    def _save_mitigated_ips(self):
        """Save mitigated IPs to file."""
        try:
            data = {
                'mitigated_ips': list(self.mitigated_ips),
                'last_updated': int(time.time())
            }
            with open(MITIGATED_IPS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"❌ Error saving mitigated IPs: {e}")
    
    def _add_mitigated_ip(self, ip_address):
        """Add an IP to the mitigated IPs list."""
        with self.mitigated_ips_lock:
            if ip_address not in self.mitigated_ips:
                self.mitigated_ips.add(ip_address)
                self._save_mitigated_ips()
                print(f"📋 Added {ip_address} to mitigated IPs list (total: {len(self.mitigated_ips)})")
    
    def _is_ip_already_mitigated(self, ip_address):
        """Check if an IP has already been mitigated."""
        with self.mitigated_ips_lock:
            return ip_address in self.mitigated_ips
    
    def _add_to_pending_blocks(self, ip_address):
        """Add IP to pending blocks queue for batch processing."""
        if self.is_ip_whitelisted(ip_address):
            print(f"⚠️ SKIPPING BATCH ADD: {ip_address} is whitelisted and will not be blocked")
            return
            
        if self._is_ip_already_mitigated(ip_address):
            print(f"⚠️ SKIPPING BATCH ADD: {ip_address} has already been mitigated to Cloudflare")
            return
            
        with self.pending_blocks_lock:
            if ip_address not in self.pending_blocks:
                self.pending_blocks.add(ip_address)
                print(f"📋 Added {ip_address} to pending blocks queue (total queued: {len(self.pending_blocks)})")
                
                if self.batch_block_timer is None:
                    self._start_batch_block_timer()
    
    def _start_batch_block_timer(self):
        """Start the batch blocking timer."""
        if self.batch_block_timer is not None:
            self.batch_block_timer.cancel()
        
        self.batch_block_timer = threading.Timer(self.batch_block_interval, self._process_batch_blocks)
        self.batch_block_timer.start()
        print(f"⏱️ Started batch block timer - processing in {self.batch_block_interval} seconds")
    
    def _process_batch_blocks(self):
        """Process all pending blocks in a batch."""
        with self.pending_blocks_lock:
            if not self.pending_blocks:
                self.batch_block_timer = None
                return
            
            ips_to_block = list(self.pending_blocks)
            self.pending_blocks.clear()
            self.batch_block_timer = None
        
        print(f"🚀 BATCH BLOCKING: Processing {len(ips_to_block)} IPs: {', '.join(ips_to_block)}")
        
        for ip_address in ips_to_block:
            if not self._is_ip_already_mitigated(ip_address) and not self.is_ip_whitelisted(ip_address):
                self._block_ip_with_cloudflare_now(ip_address)
        
        print(f"✅ BATCH BLOCKING: Completed processing {len(ips_to_block)} IPs")
    
    def is_ip_whitelisted(self, ip_address):
        """Check if an IP address is whitelisted."""
        return ip_address in self.whitelisted_ips
        
    def record_request(self, client_ip=None, request_path=None, user_agent=None):
        current_time = time.time()
        self.request_count += 1
        
        if client_ip:
            if not self.is_ip_whitelisted(client_ip):
                self._track_ip_requests(client_ip, current_time)
                if request_path:
                    self._track_request_patterns(client_ip, request_path, user_agent, current_time)
            else:
                if client_ip not in self.ip_requests:
                    self.ip_requests[client_ip] = 0
                    self.ip_last_reset[client_ip] = current_time
                self.ip_requests[client_ip] += 1
                
                if current_time - self.ip_last_reset[client_ip] >= 1.0:
                    self.ip_requests[client_ip] = 0
                    self.ip_last_reset[client_ip] = current_time
        
        if current_time - self.last_reset >= 1.0:
            current_rps = self.request_count
            self.request_count = 0
            self.last_reset = current_time
            
            if current_rps >= self.attack_threshold:
                if self.attack_start_time is None:
                    self.attack_start_time = current_time
                    self.attack_request_count = 0
                    self.peak_rps = current_rps
                    
                    ip_stats = self._get_ip_attack_stats()
                    print(f"🚨 HIGH TRAFFIC: {current_rps} RPS from {ip_stats['unique_ips']} unique IPs")
                    if ip_stats['top_spammers']:
                        print(f"🎯 Top spammers: {ip_stats['top_spammers']}")
                
                self.attack_request_count += current_rps
                self.peak_rps = max(self.peak_rps, current_rps)
                
                if current_time - self.last_attack_log >= 10.0:
                    attack_duration = current_time - self.attack_start_time
                    ip_stats = self._get_ip_attack_stats()
                    print(f"🚨 ATTACK: {current_rps} RPS | {attack_duration:.0f}s | {self.attack_request_count} total | {ip_stats['unique_ips']} IPs")
                    if ip_stats['top_spammers']:
                        print(f"🎯 Top spammers: {ip_stats['top_spammers']}")
                        self._block_top_spammers(ip_stats['top_ips_data'])
                        if ip_stats['unique_ips'] > 100:
                            self._block_all_top_spammers(ip_stats['top_ips_data'])
                    self.last_attack_log = current_time
                
            elif self.attack_start_time is not None:
                attack_duration = current_time - self.attack_start_time
                print(f"✅ ENDED: {current_rps} RPS | {attack_duration:.0f}s | {self.attack_request_count} total")
                
                self.total_attack_stats['total_duration'] += attack_duration
                self.total_attack_stats['total_requests'] += self.attack_request_count
                self.total_attack_stats['max_peak_rps'] = max(self.total_attack_stats['max_peak_rps'], self.peak_rps)
                self.total_attack_stats['attack_count'] += 1
                self.total_attack_stats['mitigation_time'] = attack_duration
                
                self._schedule_delayed_notification()
                
                self.attack_start_time = None
                self.attack_request_count = 0
                self.last_attack_log = 0
                self.peak_rps = 0
    
    def _track_ip_requests(self, client_ip, current_time):
        """Track requests per IP and block if single IP spam is detected."""
        if self.is_ip_whitelisted(client_ip):
            return
            
        if client_ip not in self.ip_requests:
            self.ip_requests[client_ip] = 0
            self.ip_last_reset[client_ip] = current_time
        
        self.ip_requests[client_ip] += 1
        
        if current_time - self.ip_last_reset[client_ip] >= 1.0:
            ip_rps = self.ip_requests[client_ip]
            
            if ip_rps >= self.single_ip_threshold and client_ip not in self.blocked_ips:
                print(f"🚨 SINGLE IP SPAM DETECTED: {client_ip} sending {ip_rps} RPS")
                self._block_ip_with_cloudflare(client_ip)
            
            self.ip_requests[client_ip] = 0
            self.ip_last_reset[client_ip] = current_time
    
    def _block_ip_with_cloudflare_now(self, ip_address):
        """Block IP address using Cloudflare IP Access Rules for 1 hour - immediate blocking."""
        if self.is_ip_whitelisted(ip_address):
            print(f"⚠️ SKIPPING BLOCK: {ip_address} is whitelisted and will not be blocked")
            return
            
        if self._is_ip_already_mitigated(ip_address):
            print(f"⚠️ SKIPPING BLOCK: {ip_address} has already been mitigated to Cloudflare")
            return
            
        try:
            import requests
            
            account_id = "47f966ebd53194d136472e51bc638a86"
            zone_id = "5e27f8358d3cce98e9ab06ddddda3ddf"
            api_key = "2aa2355ba5dde55b61291cb7f29b0519d4bf6"
            
            headers = {
                "X-Auth-Email": "Sunny985@dcpa.net",
                "X-Auth-Key": api_key,
                "Content-Type": "application/json"
            }
            
            list_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/access_rules/rules"
            params = {
                "configuration.target": "ip",
                "configuration.value": ip_address,
                "mode": "block"
            }
            
            list_response = requests.get(list_url, headers=headers, params=params)
            
            if list_response.status_code == 200:
                list_result = list_response.json()
                if list_result.get("success") and list_result.get("result"):
                    existing_rules = list_result["result"]
                    if existing_rules:
                        existing_rule = existing_rules[0]
                        rule_id = existing_rule.get("id")
                        print(f"⚠️ IP {ip_address} is already blocked by Cloudflare (Rule ID: {rule_id})")
                        
                        unblock_timer = threading.Timer(self.block_duration, self._unblock_ip_from_cloudflare, args=[ip_address, rule_id])
                        unblock_timer.start()
                        
                        self.blocked_ips[ip_address] = {
                            'blocked_at': time.time(),
                            'unblock_timer': unblock_timer,
                            'rule_id': rule_id,
                            'rule_type': 'ip_access'
                        }
                        
                        self._add_mitigated_ip(ip_address)
                        self._schedule_ip_blocking_notification(ip_address)
                        return
            
            rule_data = {
                "mode": "block",
                "configuration": {
                    "target": "ip",
                    "value": ip_address
                },
                "notes": f"ExoML-Auto-Block-{int(time.time())}"
            }
            
            ip_access_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/access_rules/rules"
            response = requests.post(ip_access_url, headers=headers, json=rule_data)
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                if result.get("success"):
                    rule_id = result.get("result", {}).get("id")
                    print(f"✅ Successfully blocked IP {ip_address} with Cloudflare IP Access Rules (Rule ID: {rule_id})")
                    
                    unblock_timer = threading.Timer(self.block_duration, self._unblock_ip_from_cloudflare, args=[ip_address, rule_id])
                    unblock_timer.start()
                    
                    self.blocked_ips[ip_address] = {
                        'blocked_at': time.time(),
                        'unblock_timer': unblock_timer,
                        'rule_id': rule_id,
                        'rule_type': 'ip_access'
                    }
                    
                    self._add_mitigated_ip(ip_address)
                    self._schedule_ip_blocking_notification(ip_address)
                else:
                    print(f"❌ Cloudflare API returned success=false: {result.get('errors')}")
            elif response.status_code == 400:
                try:
                    error_result = response.json()
                    errors = error_result.get("errors", [])
                    
                    duplicate_error = any(
                        error.get("code") == 10009 or "duplicate" in error.get("message", "").lower()
                        for error in errors
                    )
                    
                    if duplicate_error:
                        print(f"⚠️ IP {ip_address} already has a blocking rule in Cloudflare (duplicate detected)")
                        self.blocked_ips[ip_address] = {
                            'blocked_at': time.time(),
                            'unblock_timer': None,
                            'rule_id': None,
                            'rule_type': 'ip_access'
                        }
                        
                        self._add_mitigated_ip(ip_address)
                        self._schedule_ip_blocking_notification(ip_address)
                    else:
                        print(f"❌ Cloudflare API error 400: {response.text}")
                except json.JSONDecodeError:
                    print(f"❌ Cloudflare API error 400 (unparseable): {response.text}")
            elif response.status_code == 429:
                print(f"⚠️ Cloudflare API rate limit hit for IP {ip_address}. Adding to mitigated list to prevent retries.")
                self._add_mitigated_ip(ip_address)
                self.blocked_ips[ip_address] = {
                    'blocked_at': time.time(),
                    'unblock_timer': None,
                    'rule_id': None,
                    'rule_type': 'rate_limited'
                }
                self._schedule_ip_blocking_notification(ip_address)
            else:
                print(f"❌ Cloudflare API error: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Error blocking IP {ip_address} with Cloudflare: {e}")
    
    def _block_ip_with_cloudflare(self, ip_address):
        """Add IP to batch blocking queue instead of immediate blocking."""
        self._add_to_pending_blocks(ip_address)
    
    def _unblock_ip_from_cloudflare(self, ip_address, rule_id=None):
        """Unblock IP address from Cloudflare IP Access Rules or WAF."""
        try:
            import requests
            
            account_id = "47f966ebd53194d136472e51bc638a86"
            zone_id = "5e27f8358d3cce98e9ab06ddddda3ddf"
            api_key = "2aa2355ba5dde55b61291cb7f29b0519d4bf6"
            
            rule_type = 'ip_access'
            if rule_id is None and ip_address in self.blocked_ips:
                rule_id = self.blocked_ips[ip_address].get('rule_id')
                rule_type = self.blocked_ips[ip_address].get('rule_type', 'ip_access')
            
            if rule_id:
                headers = {
                    "X-Auth-Email": "Sunny985@dcpa.net",
                    "X-Auth-Key": api_key,
                    "Content-Type": "application/json"
                }
                
                if rule_type == 'ip_access':
                    access_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/access_rules/rules/{rule_id}"
                    response = requests.delete(access_url, headers=headers)
                    rule_type_display = "IP Access Rules"
                else:
                    waf_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/rules/{rule_id}"
                    response = requests.delete(waf_url, headers=headers)
                    rule_type_display = "WAF"
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        print(f"✅ Successfully unblocked IP {ip_address} from Cloudflare {rule_type_display} (Rule ID: {rule_id})")
                    else:
                        print(f"❌ Cloudflare API returned success=false: {result.get('errors')}")
                else:
                    print(f"❌ Cloudflare API error: {response.status_code} - {response.text}")
            else:
                print(f"⚠️ No rule ID found for IP {ip_address}, cannot unblock from Cloudflare")
            
            if ip_address in self.blocked_ips:
                del self.blocked_ips[ip_address]
                
        except Exception as e:
            print(f"❌ Error unblocking IP {ip_address} from Cloudflare: {e}")
    
    def is_ip_blocked(self, ip_address):
        """Check if an IP address is currently blocked."""
        return ip_address in self.blocked_ips
    
    def cleanup_blocked_ips_on_startup(self):
        """Clear all blocked IPs on server startup since timers are lost on restart."""
        if self.blocked_ips:
            print(f"🧹 STARTUP CLEANUP: Clearing {len(self.blocked_ips)} blocked IPs from previous session")
            for ip in list(self.blocked_ips.keys()):
                print(f"🔓 STARTUP UNBLOCK: {ip}")
            self.blocked_ips.clear()
        else:
            print("🧹 STARTUP CLEANUP: No blocked IPs to clear")
        
        with self.mitigated_ips_lock:
            if self.mitigated_ips:
                print(f"🧹 STARTUP CLEANUP: Clearing {len(self.mitigated_ips)} mitigated IPs from previous session")
                self.mitigated_ips.clear()
                self._save_mitigated_ips()
            else:
                print("🧹 STARTUP CLEANUP: No mitigated IPs to clear")
        
        self._clear_all_cloudflare_auto_block_rules()
    
    def _clear_all_cloudflare_auto_block_rules(self):
        """Clear all ExoML auto-block rules from Cloudflare on startup."""
        try:
            import requests
            
            zone_id = "5e27f8358d3cce98e9ab06ddddda3ddf"
            api_key = "2aa2355ba5dde55b61291cb7f29b0519d4bf6"
            
            headers = {
                "X-Auth-Email": "Sunny985@dcpa.net",
                "X-Auth-Key": api_key,
                "Content-Type": "application/json"
            }
            
            list_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/access_rules/rules"
            
            print("🧹 STARTUP CLEANUP: Fetching Cloudflare IP Access Rules...")
            response = requests.get(list_url, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("result"):
                    rules = result["result"]
                    
                    exoml_rules = []
                    for rule in rules:
                        notes = rule.get("notes", "")
                        if notes.startswith("ExoML-Auto-Block-"):
                            exoml_rules.append(rule)
                    
                    if exoml_rules:
                        print(f"🧹 STARTUP CLEANUP: Found {len(exoml_rules)} ExoML auto-block rules to delete")
                        
                        deleted_count = 0
                        for rule in exoml_rules:
                            rule_id = rule.get("id")
                            target_ip = rule.get("configuration", {}).get("value", "unknown")
                            
                            delete_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/access_rules/rules/{rule_id}"
                            delete_response = requests.delete(delete_url, headers=headers)
                            
                            if delete_response.status_code == 200:
                                delete_result = delete_response.json()
                                if delete_result.get("success"):
                                    print(f"🔓 STARTUP CLEANUP: Deleted rule for IP {target_ip} (Rule ID: {rule_id})")
                                    deleted_count += 1
                                else:
                                    print(f"❌ STARTUP CLEANUP: Failed to delete rule for IP {target_ip}: {delete_result.get('errors')}")
                            else:
                                print(f"❌ STARTUP CLEANUP: API error deleting rule for IP {target_ip}: {delete_response.status_code}")
                        
                        print(f"✅ STARTUP CLEANUP: Successfully deleted {deleted_count}/{len(exoml_rules)} ExoML auto-block rules")
                    else:
                        print("🧹 STARTUP CLEANUP: No ExoML auto-block rules found in Cloudflare")
                else:
                    print(f"❌ STARTUP CLEANUP: Cloudflare API returned success=false: {result.get('errors')}")
            else:
                print(f"❌ STARTUP CLEANUP: Failed to fetch Cloudflare rules: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ STARTUP CLEANUP: Error clearing Cloudflare auto-block rules: {e}")
    
    def _get_ip_attack_stats(self):
        """Get statistics about IPs during an attack."""
        ip_counts = {}
        for ip, count in self.ip_requests.items():
            if count > 0:
                ip_counts[ip] = count
        
        unique_ips = len(ip_counts)
        
        sorted_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)
        
        top_spammers = []
        top_ips_data = []
        for ip, count in sorted_ips[:5]:
            top_spammers.append(f"{ip}({count})")
            top_ips_data.append((ip, count))
        
        return {
            'unique_ips': unique_ips,
            'top_spammers': ', '.join(top_spammers) if top_spammers else None,
            'top_ips_data': top_ips_data
        }
    
    def _block_top_spammers(self, top_ips_data):
        """Block IPs that exceed the individual spam threshold."""
        for ip, count in top_ips_data:
            if count >= self.single_ip_threshold and ip not in self.blocked_ips and not self.is_ip_whitelisted(ip):
                print(f"🚨 BLOCKING TOP SPAMMER: {ip} with {count} RPS")
                self._block_ip_with_cloudflare(ip)
    
    def _block_all_top_spammers(self, top_ips_data):
        """Block all top spamming IPs regardless of threshold during large-scale attacks."""
        for i, (ip, count) in enumerate(top_ips_data):
            if ip not in self.blocked_ips and i < 4 and not self.is_ip_whitelisted(ip):
                print(f"🚨 BLOCKING TOP SPAMMER (LARGE-SCALE ATTACK): {ip} with {count} RPS")
                self._block_ip_with_cloudflare(ip)
    
    def _track_request_patterns(self, client_ip, request_path, user_agent, current_time):
        """Track request patterns to detect malicious behavior."""
        if client_ip not in self.ip_patterns:
            self.ip_patterns[client_ip] = {
                'paths': {},
                'user_agents': {},
                'last_cleanup': current_time,
                'total_requests': 0,
                'suspicious_score': 0
            }
        
        patterns = self.ip_patterns[client_ip]
        patterns['total_requests'] += 1
        
        if current_time - patterns['last_cleanup'] > self.pattern_window:
            patterns['paths'].clear()
            patterns['user_agents'].clear()
            patterns['last_cleanup'] = current_time
            patterns['total_requests'] = 1
            patterns['suspicious_score'] = 0
        
        if request_path:
            patterns['paths'][request_path] = patterns['paths'].get(request_path, 0) + 1
        
        if user_agent:
            patterns['user_agents'][user_agent] = patterns['user_agents'].get(user_agent, 0) + 1
        
        self._calculate_suspicious_score(client_ip, patterns)
        
        current_time = time.time()
        recent_requests = 0
        
        if client_ip in self.ip_requests:
            recent_requests = self.ip_requests[client_ip]
        
        if (patterns['suspicious_score'] >= 150 and
            recent_requests >= self.single_ip_threshold and
            patterns['total_requests'] >= self.malicious_threshold and
            client_ip not in self.blocked_ips and
            not self.is_ip_whitelisted(client_ip)):
            
            print(f"🚨 MALICIOUS PATTERN DETECTED: {client_ip} (Score: {patterns['suspicious_score']}, Requests: {patterns['total_requests']}, Current RPS: {recent_requests})")
            self._log_malicious_patterns(client_ip, patterns)
            self._block_ip_with_cloudflare(client_ip)
    
    def _calculate_suspicious_score(self, client_ip, patterns):
        """Calculate a suspicious score based on request patterns - focus on actual malicious behavior, not volume."""
        score = 0
        
        
        if patterns['user_agents']:
            for ua, count in patterns['user_agents'].items():
                if ua and (
                    'curl' in ua.lower() or
                    'wget' in ua.lower() or
                    len(ua) < 5
                ):
                    score += 30
        
        if patterns['user_agents']:
            for ua in patterns['user_agents'].keys():
                if ua and any(attack_tool in ua.lower() for attack_tool in ['nikto', 'sqlmap', 'nmap', 'dirb', 'gobuster']):
                    score += 50
        
        
        patterns['suspicious_score'] = score
    
    def _log_malicious_patterns(self, client_ip, patterns):
        """Log details about detected malicious patterns."""
        print(f"🔍 MALICIOUS PATTERN DETAILS for {client_ip}:")
        print(f"   📊 Total requests: {patterns['total_requests']}")
        print(f"   🎯 Suspicious score: {patterns['suspicious_score']}")
        
        if patterns['paths']:
            top_paths = sorted(patterns['paths'].items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"   🛤️  Top paths: {top_paths}")
        
        if patterns['user_agents']:
            print(f"   🤖 User agents: {list(patterns['user_agents'].keys())[:2]}")
    
    
    def _schedule_delayed_notification(self):
        """Schedule a delayed notification to prevent webhook spam."""
        if self.notification_timer:
            self.notification_timer.cancel()
        
        self.notification_timer = threading.Timer(
            self.cooldown_duration,
            self._send_combined_notification
        )
        self.notification_timer.start()
        print(f"⏳ Discord notification scheduled in {self.cooldown_duration}s (anti-spam protection)")
    
    def _send_combined_notification(self):
        """Send combined notification for all attacks in the cooldown period."""
        if self.total_attack_stats['attack_count'] == 0:
            return
            
        stats = self.total_attack_stats
        avg_rps = stats['total_requests'] / stats['total_duration'] if stats['total_duration'] > 0 else 0
        
        blocked_ips_list = list(self.blocked_ips.keys())
        
        mitigation_time = stats.get('mitigation_time', 0)
        
        self._send_discord_notification(
            stats['total_duration'],
            stats['total_requests'],
            avg_rps,
            stats['max_peak_rps'],
            stats['attack_count'],
            blocked_ips_list,
            mitigation_time
        )
        
        self.total_attack_stats = {
            'total_duration': 0.0,
            'total_requests': 0,
            'max_peak_rps': 0,
            'attack_count': 0
        }
        self.notification_timer = None
    
    def _schedule_ip_blocking_notification(self, blocked_ip):
        """Schedule a delayed notification for IP blocking to prevent webhook spam."""
        self.pending_blocked_ips.append({
            'ip': blocked_ip,
            'blocked_at': time.time()
        })
        print(f"📋 Added {blocked_ip} to pending blocked IPs list")
        
        if self.ip_blocking_timer:
            self.ip_blocking_timer.cancel()
        
        self.ip_blocking_timer = threading.Timer(
            self.cooldown_duration,
            self._send_combined_ip_blocking_notification
        )
        self.ip_blocking_timer.start()
        print(f"⏳ IP blocking Discord notification scheduled in {self.cooldown_duration}s (anti-spam protection)")
    
    def _send_combined_ip_blocking_notification(self):
        """Send combined notification for all IPs blocked in the cooldown period."""
        if not self.pending_blocked_ips:
            return
        
        all_ips = [entry['ip'] for entry in self.pending_blocked_ips]
        blocked_ips_list = list(set(all_ips))
        blocked_count = len(blocked_ips_list)
        
        print(f"📊 IP blocking notification: {len(all_ips)} total blocks, {blocked_count} unique IPs")
        
        self._send_ip_blocking_discord_notification(blocked_ips_list, blocked_count)
        
        self.pending_blocked_ips = []
        self.ip_blocking_timer = None
    
    def _send_ip_blocking_discord_notification(self, blocked_ips_list, blocked_count):
        """Send IP blocking notification to Discord webhook."""
        import urllib.request
        import urllib.error
        import json
        
        try:
            if blocked_count == 1:
                title = "🚫 IP Address Blocked"
                description = f"Automatically blocked 1 IP address due to spam detection"
            else:
                title = f"🚫 Multiple IPs Blocked ({blocked_count} IPs)"
                description = f"Automatically blocked {blocked_count} IP addresses due to spam detection"
            
            fields = [
                {"name": "🔢 Total Blocked", "value": f"{blocked_count}", "inline": True},
                {"name": "⏱️ Block Duration", "value": "1 hour", "inline": True},
                {"name": "🛡️ Protection", "value": "Cloudflare IP Access Rules", "inline": True}
            ]
            
            if blocked_ips_list:
                if len(blocked_ips_list) <= 10:
                    blocked_ips_text = "\n".join([f"`{ip}`" for ip in blocked_ips_list])
                else:
                    blocked_ips_text = "\n".join([f"`{ip}`" for ip in blocked_ips_list[:10]]) + f"\n... and {len(blocked_ips_list) - 10} more"
                fields.append({"name": "🎯 Blocked IPs", "value": blocked_ips_text, "inline": False})
            
            embed = {
                "title": title,
                "description": description,
                "color": 0xff9900,
                "fields": fields,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "footer": {"text": "ExoML API Server - Automatic IP blocking system"}
            }
            
            payload = {"embeds": [embed]}
            data = json.dumps(payload).encode('utf-8')
            
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'ExoML-Server/1.0'
                }
            )
            
            with urllib.request.urlopen(req) as response:
                if response.status == 204:
                    print("✅ IP blocking Discord notification sent")
                else:
                    print(f"⚠️ Discord webhook returned status {response.status}")
                    
        except urllib.error.HTTPError as e:
            print(f"❌ Discord webhook HTTP error {e.code}: {e.reason}")
        except Exception as e:
            print(f"❌ Failed to send IP blocking Discord notification: {e}")
    
    def _send_discord_notification(self, duration, total_requests, avg_rps, peak_rps, attack_count=1, blocked_ips_list=None, mitigation_time=0):
        """Send attack summary to Discord webhook."""
        import urllib.request
        import urllib.error
        import json
        
        try:
            if attack_count == 1:
                title = "🛡️ Attack Ended"
                description = "Single attack detected and handled"
            else:
                title = f"🛡️ Attack Wave Ended ({attack_count} attacks)"
                description = f"Multiple attacks detected within 60 seconds - combined report"
            
            fields = [
                {"name": "⏱️ Total Duration", "value": f"{duration:.1f} seconds", "inline": True},
                {"name": "📊 Total Requests", "value": f"{total_requests:,}", "inline": True},
                {"name": "📈 Peak RPS", "value": f"{peak_rps:,}", "inline": True},
                {"name": "📉 Average RPS", "value": f"{avg_rps:.1f}", "inline": True},
                {"name": "🔢 Attack Count", "value": f"{attack_count}", "inline": True},
                {"name": "🎯 Status", "value": "Server handled successfully", "inline": False}
            ]
            
            if blocked_ips_list and len(blocked_ips_list) > 0:
                if len(blocked_ips_list) <= 5:
                    blocked_ips_text = "\n".join([f"`{ip}`" for ip in blocked_ips_list])
                else:
                    blocked_ips_text = "\n".join([f"`{ip}`" for ip in blocked_ips_list[:5]]) + f"\n... and {len(blocked_ips_list) - 5} more"
                fields.append({"name": "🚫 Blocked IPs", "value": blocked_ips_text, "inline": False})
            
            if mitigation_time > 0:
                fields.append({"name": "⚡ Mitigated in", "value": f"{mitigation_time:.1f} seconds", "inline": True})
            
            embed = {
                "title": title,
                "description": description,
                "color": 0x00ff00,
                "fields": fields,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "footer": {"text": "ExoML API Server - Anti-spam protection active"}
            }
            
            payload = {"embeds": [embed]}
            data = json.dumps(payload).encode('utf-8')
            
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'ExoML-Server/1.0'
                }
            )
            
            with urllib.request.urlopen(req) as response:
                if response.status == 204:
                    print("✅ Discord notification sent")
                else:
                    print(f"⚠️ Discord webhook returned status {response.status}")
                    
        except urllib.error.HTTPError as e:
            print(f"❌ Discord webhook HTTP error {e.code}: {e.reason}")
        except Exception as e:
            print(f"❌ Failed to send Discord notification: {e}")

rate_monitor = RequestRateMonitor()

def save_users_config_safely(config_data):
    """Saves the user configuration to a temporary file and then renames it."""
    temp_file_path = USERS_CONFIG_FILE + ".tmp"
    try:
        with open(temp_file_path, 'w') as f:
            json.dump(config_data, f, indent=4)
        os.rename(temp_file_path, USERS_CONFIG_FILE)
        raprint(f"Safely saved updated user configuration to {USERS_CONFIG_FILE}")
        return True
    except Exception as e:
        raprint(f"ERROR: Failed to save user configuration safely: {e}")
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as remove_e:
                raprint(f"ERROR: Failed to remove temporary user config file {temp_file_path}: {remove_e}")
        return False
def save_providers_config_safely(config_data):
    """Saves the provider configuration to a temporary file and then renames it."""
    temp_file_path = CONFIG_FILE + ".tmp"
    try:
        with open(temp_file_path, 'w') as f:
            json.dump(config_data, f, indent=4)
        os.rename(temp_file_path, CONFIG_FILE)
        raprint(f"Safely saved updated provider configuration to {CONFIG_FILE}")
        return True
    except Exception as e:
        raprint(f"ERROR: Failed to save provider configuration safely: {e}")
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as remove_e:
                raprint(f"ERROR: Failed to remove temporary provider config file {temp_file_path}: {remove_e}")
        return False

def raprint(*text):
    if text and len(text) > 0:
        text_str = str(text[0]) if text else ""
        if ("Updated token count" in text_str or "HIGH TRAFFIC" in text_str or
            "ATTACK" in text_str or "CRITICAL ERROR" in text_str):
            print(*text)
        print(*text)

def remove_provider(endpoint_path, model_id, provider_details):
    """Removes a specific provider from the configuration and saves the change."""
    return
    with providers_config_lock:
        global providers_config
        try:
            with open(CONFIG_FILE, 'r') as f:
                current_providers_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raprint(f"ERROR: Could not load providers config to remove provider: {e}")
            return

        if endpoint_path in current_providers_config.get("endpoints", {}) and \
           model_id in current_providers_config["endpoints"][endpoint_path].get("models", {}):
            
            providers_list = current_providers_config["endpoints"][endpoint_path]["models"][model_id]
            
            provider_to_remove = None
            for p in providers_list:
                if p.get('base_url') == provider_details.get('base_url') and \
                   p.get('api_key') == provider_details.get('api_key'):
                    provider_to_remove = p
                    break
            
            if provider_to_remove:
                providers_list.remove(provider_to_remove)
                raprint(f"Removed provider {provider_details.get('provider_name')} for model {model_id} from {endpoint_path}")
                if save_providers_config_safely(current_providers_config):
                    providers_config = current_providers_config
                    global AVAILABLE_MODELS_LIST
                    AVAILABLE_MODELS_LIST = _generate_models_list(providers_config)
                else:
                    raprint(f"CRITICAL ERROR: Failed to save providers config after removing provider.")
            else:
                raprint(f"Provider not found for removal: {provider_details}")

def rotate_and_save_providers(endpoint_path, model_id, successful_provider):
    """Rotates the provider list for a given model and saves the configuration."""
    with providers_config_lock:
        global providers_config
        
        priority = successful_provider.get('priority', 99)
        base_url = successful_provider.get('base_url')
        
        providers_list = providers_config["endpoints"][endpoint_path]["models"][model_id]
        
        group_to_rotate = [p for p in providers_list if p.get('priority', 99) == priority and p.get('base_url') == base_url]
        
        if len(group_to_rotate) > 1:
            rotated_group = group_to_rotate[1:] + group_to_rotate[:1]
            
            start_index = -1
            for i, p in enumerate(providers_list):
                if p.get('priority', 99) == priority and p.get('base_url') == base_url:
                    start_index = i
                    break
            
            if start_index != -1:
                providers_list[start_index:start_index + len(rotated_group)] = rotated_group
                raprint(f"Rotated providers for model {model_id} at {endpoint_path}")
                save_providers_config_safely(providers_config)
                global AVAILABLE_MODELS_LIST
                AVAILABLE_MODELS_LIST = _generate_models_list(providers_config)

def update_provider_failure_count(endpoint_path, model_id, provider_details, increment=True, remove_threshold=5):
    """Updates the consecutive failure count for a provider, removes if threshold reached."""
    with providers_config_lock:
        global providers_config
        try:
            with open(CONFIG_FILE, 'r') as f:
                current_providers_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raprint(f"ERROR: Could not load providers config to update failure count: {e}")
            return False

        if endpoint_path in current_providers_config.get("endpoints", {}) and \
           model_id in current_providers_config["endpoints"][endpoint_path].get("models", {}):

            providers_list = current_providers_config["endpoints"][endpoint_path]["models"][model_id]
            provider_to_update = None
            for p in providers_list:
                if p.get('base_url') == provider_details.get('base_url') and \
                   p.get('api_key') == provider_details.get('api_key'):
                    provider_to_update = p
                    break

            if provider_to_update:
                current_count = provider_to_update.get('consecutive_failures', 0)
                if increment:
                    new_count = current_count + 1
                    provider_to_update['consecutive_failures'] = new_count
                    if new_count >= remove_threshold:
                        raprint(f"Provider {provider_details.get('provider_name')} for model {model_id} has {new_count} consecutive failures (removal disabled).")
                    else:
                        raprint(f"Incremented failure count for provider {provider_details.get('provider_name')} to {new_count}.")
                else:
                    if current_count != 0:
                        provider_to_update['consecutive_failures'] = 0
                        raprint(f"Reset failure count for provider {provider_details.get('provider_name')} to 0 after success.")

                if save_providers_config_safely(current_providers_config):
                    providers_config = current_providers_config
                    global AVAILABLE_MODELS_LIST
                    AVAILABLE_MODELS_LIST = _generate_models_list(providers_config)
                    return True
                else:
                    raprint(f"Failed to save config after updating failure count for {provider_details.get('provider_name')}.")
                    return False
            else:
                raprint(f"Provider not found for failure count update: {provider_details}")
                return False
        else:
            raprint(f"Endpoint or model not found for failure count update: {endpoint_path}/{model_id}")
            return False
def get_daily_limit_from_plan(plan_str):
    """
    Parses plan string (e.g., '500k', '100m', 'unlimited') into an integer token limit.
    Returns None for 'unlimited'.
    """
    if not isinstance(plan_str, str):
        return 0
    plan_str = plan_str.lower().strip()

    if plan_str == "unlimited":
        return None

    multiplier = 1
    if plan_str.endswith('k'):
        multiplier = 1000
        plan_str = plan_str[:-1]
    elif plan_str.endswith('m'):
        multiplier = 1_000_000
        plan_str = plan_str[:-1]
    elif plan_str.endswith('b'):
        multiplier = 1_000_000_000
        plan_str = plan_str[:-1]

    try:
        limit = float(plan_str) * multiplier
        return int(limit)
    except ValueError:
        raprint(f"Warning: Could not parse plan string '{plan_str}'. Defaulting limit to 0.")
        return 0

def is_new_day(last_timestamp):
    """Checks if the last_timestamp is from a previous day (UTC)."""
    if not last_timestamp:
        return True
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(last_timestamp, (int, float)) or last_timestamp < 0:
        raprint(f"Warning: Invalid last_timestamp encountered ({last_timestamp}). Treating as new day.")
        return True
    try:
        last_time_utc = datetime.datetime.fromtimestamp(last_timestamp, datetime.timezone.utc)
        return now_utc.date() > last_time_utc.date()
    except Exception as e:
        raprint(f"Warning: Error converting timestamp {last_timestamp} in is_new_day: {e}. Treating as new day.")
        return True

def check_opensource_rpm_limit(api_key, rpm_limit):
    """
    Check if user has exceeded their RPM limit for opensource models.
    Returns True if request is allowed, False if limit exceeded.
    """
    if not rpm_limit or rpm_limit <= 0:
        return True
    
    with opensource_rpm_tracker_lock:
        current_time = time.time()
        current_minute = int(current_time // 60)
        
        if api_key not in opensource_rpm_tracker:
            opensource_rpm_tracker[api_key] = {}
        
        user_tracker = opensource_rpm_tracker[api_key]
        
        minutes_to_remove = [minute for minute in user_tracker.keys() if minute < current_minute]
        for minute in minutes_to_remove:
            del user_tracker[minute]
        
        current_requests = user_tracker.get(current_minute, 0)
        
        if current_requests >= rpm_limit:
            return False
        
        user_tracker[current_minute] = current_requests + 1
        return True

PREAUTH_TOKENS = 5000
def preauth_tokens(api_key, tokens_to_reserve=PREAUTH_TOKENS):
    """
    Pre-authorize tokens at request start to prevent spam.
    Returns True if successful, False if insufficient tokens.
    """
    global users_config
    
    current_users_config = users_config
    
    user_data = current_users_config.get("users", {}).get(api_key)
    if not user_data:
        return False
        
    user_plan = user_data.get("plan", "0")
    
    if user_plan == "pay2go":
        available_tokens = user_data.get("available_tokens", 0)
        if available_tokens < tokens_to_reserve:
            return False
        
        user_data['available_tokens'] = available_tokens - tokens_to_reserve
        user_data['preauth_reserved'] = user_data.get('preauth_reserved', 0) + tokens_to_reserve
        
    else:
        daily_limit = get_daily_limit_from_plan(user_plan)
        if daily_limit is not None and daily_limit >= 0:
            daily_tokens_used = user_data.get("daily_tokens_used", 0)
            last_usage_timestamp = user_data.get("last_usage_timestamp")
            
            if is_new_day(last_usage_timestamp):
                daily_tokens_used = 0
            
            if daily_tokens_used + tokens_to_reserve > daily_limit:
                return False
            
            user_data['daily_tokens_used'] = daily_tokens_used + tokens_to_reserve
            user_data['preauth_reserved'] = user_data.get('preauth_reserved', 0) + tokens_to_reserve
    
    users_config = current_users_config
    return True

def refund_preauth_tokens(api_key):
    """
    Refund pre-authorized tokens if request fails.
    """
    global users_config
    
    current_users_config = users_config
    
    user_data = current_users_config.get("users", {}).get(api_key)
    if not user_data:
        return
        
    preauth_reserved = user_data.get('preauth_reserved', 0)
    if preauth_reserved <= 0:
        return
        
    user_plan = user_data.get("plan", "0")
    
    if user_plan == "pay2go":
        available_tokens = user_data.get("available_tokens", 0)
        user_data['available_tokens'] = available_tokens + preauth_reserved
    else:
        daily_tokens_used = user_data.get("daily_tokens_used", 0)
        user_data['daily_tokens_used'] = max(0, daily_tokens_used - preauth_reserved)
    
    user_data['preauth_reserved'] = 0
    
    users_config = current_users_config

def update_user_token_count(api_key, tokens_used, token_multiplier=1.0):
    """
    Updates the token count for a given user safely, applying a multiplier.
    Also handles refunding pre-authorized tokens.

    Args:
        api_key (str): The API key of the user.
        tokens_used (int): The raw number of tokens reported by the provider.
        token_multiplier (float): The multiplier to apply before rounding up. Defaults to 1.0.
    """
    global users_config
    if not isinstance(tokens_used, int) or tokens_used < 0:
        raprint(f"Warning: Invalid token count ({tokens_used}) received for key ...{api_key[-4:]}. Skipping update.")
        return

    if not isinstance(token_multiplier, (float, int)) or token_multiplier < 0:
         raprint(f"Warning: Invalid token_multiplier ({token_multiplier}) received for key ...{api_key[-4:]}. Using 1.0.")
         token_multiplier = 1.0

    adjusted_tokens_used = math.ceil(tokens_used * token_multiplier)

    with user_config_lock:
        current_users_config = {"users": {}}
        try:
            with open(USERS_CONFIG_FILE, 'r') as f:
                current_users_config = json.load(f)
        except FileNotFoundError:
            raprint(f"Warning: User config file {USERS_CONFIG_FILE} not found during token update. Creating new structure.")
        except json.JSONDecodeError:
             raprint(f"ERROR: User config file {USERS_CONFIG_FILE} is corrupt during token update. Attempting to overwrite with current data.")
             current_users_config = users_config
        except Exception as e:
            raprint(f"ERROR: Failed to reload user config before update: {e}. Using potentially stale in-memory data.")
            current_users_config = users_config

        user_data = current_users_config.get("users", {}).get(api_key)

        if user_data:
            now_ts = int(time.time())
            total_tokens = user_data.get('total_tokens', 0)
            daily_tokens_used = user_data.get('daily_tokens_used', 0)
            last_usage_timestamp = user_data.get('last_usage_timestamp')

            if is_new_day(last_usage_timestamp):
                raprint(f"New day detected for user '{user_data.get('username', 'Unknown')}' (Key: ...{api_key[-4:]}). Resetting daily count.")
                current_daily_total = adjusted_tokens_used
            else:
                current_daily_total = daily_tokens_used + adjusted_tokens_used

            user_data['total_tokens'] = total_tokens + adjusted_tokens_used
            user_data['daily_tokens_used'] = current_daily_total
            user_data['last_usage_timestamp'] = now_ts
            user_data['last_updated_timestamp'] = now_ts

            preauth_reserved = user_data.get('preauth_reserved', 0)
            
            user_plan = user_data.get("plan", "0")
            if user_plan == "pay2go":
                available_tokens = user_data.get("available_tokens", 0)
                
                daily_free_limit = 500000
                tokens_over_free_limit = max(0, current_daily_total - daily_free_limit)
                
                if tokens_over_free_limit > 0:
                    tokens_to_deduct = min(adjusted_tokens_used, tokens_over_free_limit)
                    refund_amount = max(0, preauth_reserved - tokens_to_deduct)
                    new_available = available_tokens + refund_amount
                    user_data['available_tokens'] = new_available
                    raprint(f"Updated token count for pay2go user '{user_data.get('username', 'Unknown')}' (Key: ...{api_key[-4:]}): Used {adjusted_tokens_used} (Raw: {tokens_used}, Multiplier: {token_multiplier}). Daily total: {current_daily_total}, Over free limit: {tokens_over_free_limit}, Deducted: {tokens_to_deduct}, Refunded: {refund_amount}. Available tokens: {available_tokens} -> {new_available}")
                else:
                    refund_amount = preauth_reserved
                    new_available = available_tokens + refund_amount
                    user_data['available_tokens'] = new_available
                    raprint(f"Updated token count for pay2go user '{user_data.get('username', 'Unknown')}' (Key: ...{api_key[-4:]}): Used {adjusted_tokens_used} (Raw: {tokens_used}, Multiplier: {token_multiplier}). Daily total: {current_daily_total} (within 500k free limit). Refunded: {refund_amount}. Available tokens: {available_tokens} -> {new_available}")
            else:
                if preauth_reserved > 0:
                    user_data['daily_tokens_used'] = user_data['daily_tokens_used'] - preauth_reserved + adjusted_tokens_used
                    raprint(f"Updated token count for user '{user_data.get('username', 'Unknown')}' (Key: ...{api_key[-4:]}): Used {adjusted_tokens_used} (Raw: {tokens_used}, Multiplier: {token_multiplier}). Adjusted daily usage from pre-auth. New Daily Total: {user_data['daily_tokens_used']}. New Overall Total: {user_data['total_tokens']}")
                else:
                    raprint(f"Updated token count for user '{user_data.get('username', 'Unknown')}' (Key: ...{api_key[-4:]}): Added {adjusted_tokens_used} (Raw: {tokens_used}, Multiplier: {token_multiplier}). New Daily Total: {user_data['daily_tokens_used']}. New Overall Total: {user_data['total_tokens']}")
            
            user_data['preauth_reserved'] = 0

            users_config = current_users_config

            if not save_users_config_safely(current_users_config):
                 raprint(f"CRITICAL ERROR: Failed to save user config after token update for key ...{api_key[-4:]}")
        else:
            raprint(f"Error: Attempted to update token count for API key ...{api_key[-4:]}, but user data was not found in the loaded config during update.")


def load_configurations():
    """Loads provider and user configs, regenerates models list, returns configs."""
    global providers_config, users_config, AVAILABLE_MODELS_LIST

    loaded_providers_config = {"endpoints": {}}
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded_providers_config = json.load(f)
        raprint(f"Loaded provider configuration from {CONFIG_FILE}")
    except FileNotFoundError:
        raprint(f"ERROR: Configuration file '{CONFIG_FILE}' not found.")
    except json.JSONDecodeError:
        raprint(f"ERROR: Configuration file '{CONFIG_FILE}' contains invalid JSON.")
    except Exception as e:
        raprint(f"ERROR: Failed to load provider configuration: {e}")

    loaded_users_config = {"users": {}}
    try:
        with open(USERS_CONFIG_FILE, 'r') as f:
            loaded_users_config = json.load(f)
        raprint(f"Loaded user configuration from {USERS_CONFIG_FILE}")
    except FileNotFoundError:
        raprint(f"WARNING: User configuration file '{USERS_CONFIG_FILE}' not found. Authentication disabled.")
    except json.JSONDecodeError:
        raprint(f"ERROR: User configuration file '{USERS_CONFIG_FILE}' contains invalid JSON. Authentication disabled.")
    except Exception as e:
        raprint(f"ERROR: Failed to load user configuration: {e}. Authentication disabled.")

    providers_config = loaded_providers_config
    users_config = loaded_users_config

    AVAILABLE_MODELS_LIST = _generate_models_list(providers_config)
    raprint(f"Generated models list: {len(AVAILABLE_MODELS_LIST)} unique models found.")

    return providers_config, users_config

def setup_hackathon_key():
    """Ensures the hackathon key exists and is the only expiring key."""
    with user_config_lock:
        global users_config
        try:
            with open(USERS_CONFIG_FILE, 'r') as f:
                current_users_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            raprint(f"WARNING: Could not load {USERS_CONFIG_FILE} for hackathon key setup. Aborting.")
            return

        users_dict = current_users_config.get("users", {})
        config_changed = False

        for key, data in users_dict.items():
            if key != "sk-hackathon-2025" and "expires_at" in data:
                del data["expires_at"]
                config_changed = True
                raprint(f"Removed expiration from non-hackathon key ...{key[-4:]}")

        hackathon_key = "sk-hackathon-2025"
        hackathon_user_data = {
            "username": "hackathon",
            "user_id": "hackathon-2025",
            "plan": "unlimited",
            "enabled": True,
            "total_tokens": 0,
            "daily_tokens_used": 0,
            "last_usage_timestamp": None,
            "last_updated_timestamp": int(time.time()),
            "expires_at": "2025-07-26T00:00:00Z"
        }

        if hackathon_key not in users_dict:
            users_dict[hackathon_key] = hackathon_user_data
            config_changed = True
            raprint(f"Added new hackathon key to config.")
        else:
            key_data = users_dict[hackathon_key]
            if key_data.get("expires_at") != hackathon_user_data["expires_at"]:
                key_data["expires_at"] = hackathon_user_data["expires_at"]
                key_data["last_updated_timestamp"] = int(time.time())
                config_changed = True
                raprint(f"Updated expiration for existing hackathon key.")
            
            if key_data.get("plan") != "unlimited":
                key_data["plan"] = "unlimited"
                key_data["last_updated_timestamp"] = int(time.time())
                config_changed = True
                raprint(f"Corrected plan for existing hackathon key to 'unlimited'.")

        if config_changed:
            current_users_config["users"] = users_dict
            if save_users_config_safely(current_users_config):
                users_config = current_users_config
                raprint("Successfully saved changes for hackathon key setup.")
            else:
                raprint("CRITICAL ERROR: Failed to save user config after hackathon key setup.")

def _generate_models_list(config):
    """Generates the formatted list of models from the provider configuration."""
    models_data = {}
    current_time = int(time.time())

    if config and "endpoints" in config:
        for endpoint_path, endpoint_details in config["endpoints"].items():
            if "models" in endpoint_details:
                for model_id, providers_list in endpoint_details["models"].items():
                    if not providers_list:
                        continue

                    is_alpha_model = any(p.get("alpha", False) for p in providers_list)
                    if is_alpha_model:
                        continue

                    if model_id not in models_data:
                        owner = "unknown"
                        token_multiplier = 1.0
                        if len(providers_list) > 0 and isinstance(providers_list[0], dict):
                            if "owner" in providers_list[0]:
                                owner = providers_list[0]["owner"]
                            prov_multiplier = providers_list[0].get('token_multiplier', 1.0)
                            if isinstance(prov_multiplier, (int, float)) and prov_multiplier >= 0:
                                token_multiplier = prov_multiplier
                            else:
                                raprint(f"Warning: Invalid 'token_multiplier' ({prov_multiplier}) found for model '{model_id}' in provider '{providers_list[0].get('provider_name', 'Unknown')}' in {CONFIG_FILE}. Using default 1.0.")
                                token_multiplier = 1.0

                        models_data[model_id] = {
                            "id": model_id,
                            "object": "model",
                            "created": current_time,
                            "owned_by": owner,
                            "token_multiplier": token_multiplier,
                            "endpoint": endpoint_path
                        }

    return list(models_data.values())



class HighPerformanceProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIRECTORY, **kwargs)
        client_ip = self.get_client_ip()
        user_agent = self.headers.get('User-Agent', '')
        rate_monitor.record_request(client_ip, self.path, user_agent)
    
    def get_client_ip(self):
        """Extract the real client IP address, prioritizing Cloudflare headers."""
        cf_connecting_ip = self.headers.get('CF-Connecting-IP')
        if cf_connecting_ip:
            return cf_connecting_ip.strip()
        
        forwarded_for = self.headers.get('X-Forwarded-For')
        if forwarded_for:
            client_ip = forwarded_for.split(',')[0].strip()
            return client_ip
        
        real_ip = self.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        
        if hasattr(self, 'client_address') and self.client_address:
            return self.client_address[0]
        
        return "unknown"
    
    def _check_ip_blocked(self, requested_model=None):
        """Check if the client IP is blocked and reject the request if so."""
        client_ip = self.get_client_ip()
        
        if requested_model and requested_model in OPENSOURCE_MODELS:
            auth_header = self.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                api_key = auth_header.split(' ')[1]
                user_info = users_config.get("users", {}).get(api_key)
                if user_info and user_info.get("opensource", False):
                    return False
        
        if rate_monitor.is_ip_blocked(client_ip):
            self._send_json_response(429, {
                "error": {
                    "message": f"Your IP address {client_ip} is temporarily blocked due to spam detection. Please try again later.",
                    "type": "ip_blocked",
                    "code": "ip_temporarily_blocked"
                }
            })
            return True
        return False
    
    def log_request(self, code='-', size='-'):
        pass
    
    def log_error(self, format, *args):
        pass
    
    def log_message(self, format, *args):
        pass

    def _log_api_request(self, model):
        """Logs the user and model for an API request."""
        if hasattr(self, 'authenticated_user_info') and model:
            user_identifier = self.authenticated_user_info.get('user_id') or self.authenticated_user_info.get('username', 'N/A')
            print(f"API Request by {user_identifier} for model {model}")

    def _send_json_response(self, status_code, data):
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            response_body = json.dumps(data).encode('utf-8')
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
            raprint(f"Client disconnected during response: {e}")
        except Exception as e:
            raprint(f"Error sending JSON response: {e}")

    def end_headers(self):
        try:
            if self.command != 'OPTIONS':
                raprint(f"DEBUG: Adding standard CORS headers for non-OPTIONS request: {self.path}, method: {self.command}")
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            super().end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
            raprint(f"Client disconnected during headers: {e}")
        except Exception as e:
            raprint(f"Error sending headers: {e}")


    def _authenticate_request(self, requested_model=None):
        """Checks the Authorization header for a valid API key and model access permissions."""
        if not users_config or not users_config.get("users"):
            raprint("Authentication disabled or no users configured.")
            return True

        auth_header = self.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raprint("Authentication failed: Authorization header missing or invalid format")
            self._send_json_response(401, {"error": "Authorization header missing or invalid format (Bearer <key> required)."})
            return False

        api_key = auth_header.split(' ')[1]
        
        if api_key == OPENSOURCE_SK_TEST_KEY:
            raprint(f"Direct usage of sk-test key blocked from IP: {self.get_client_ip()}")
            self._send_json_response(403, {
                "error": {
                    "message": "This API key cannot be used directly. It is reserved for internal system operations.",
                    "type": "forbidden_key",
                    "code": "sk_test_direct_usage_blocked"
                }
            })
            return False
        
        is_opensource_model = requested_model in OPENSOURCE_MODELS if requested_model else False

        if api_key == "sk-hackathon-2025":
            client_ip = self.get_client_ip()
            with hackathon_key_rate_limiter_lock:
                current_time = time.time()
                last_request_time = hackathon_key_rate_limiter.get(client_ip)

                if last_request_time and (current_time - last_request_time) < 60:
                    raprint(f"Hackathon key rate limit exceeded for IP: {client_ip}")
                    self._send_json_response(429, {
                        "error": {
                            "message": "Rate limit exceeded for this key. Please wait one minute before your next request.",
                            "type": "rate_limit_exceeded",
                            "code": "hackathon_key_rate_limit"
                        }
                    })
                    return False
                
                hackathon_key_rate_limiter[client_ip] = current_time

        user_info = users_config.get("users", {}).get(api_key)

        if not user_info or not user_info.get("enabled", False):
            raprint(f"Authentication failed: Invalid or disabled API key ...{api_key[-4:]} - User: ...{api_key[-4:]}")
            self._send_json_response(403, {"error": "Invalid or disabled API key."})
            return False

        if is_opensource_model:
            user_has_opensource = user_info.get("opensource", False)
            if user_has_opensource:
                opensource_rpm = user_info.get("opensource_rpm", 0)
                if not check_opensource_rpm_limit(api_key, opensource_rpm):
                    raprint(f"User {user_info.get('username', 'Unknown')} (Key: ...{api_key[-4:]}) exceeded RPM limit ({opensource_rpm}) for opensource models")
                    self._send_json_response(429, {
                        "error": {
                            "message": f"You have exceeded your rate limit of {opensource_rpm} requests per minute for opensource models. Please wait before making another request.",
                            "type": "rate_limit_exceeded",
                            "code": "opensource_rpm_limit_exceeded"
                        }
                    })
                    return False
                
                raprint(f"Opensource model access granted for '{requested_model}' to user {user_info.get('username', 'Unknown')} (RPM limit: {opensource_rpm}) - using free tokens")
            else:
                raprint(f"User {user_info.get('username', 'Unknown')} (Key: ...{api_key[-4:]}) accessing opensource model '{requested_model}' - will be charged their own tokens")

        expires_at_str = user_info.get("expires_at")
        if expires_at_str:
            try:
                expires_at_dt = datetime.datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                if datetime.datetime.now(datetime.timezone.utc) > expires_at_dt:
                    raprint(f"Authentication failed: API key ...{api_key[-4:]} for user '{user_info.get('username', 'Unknown')}' has expired on {expires_at_str}.")
                    self._send_json_response(403, {"error": "API key has expired."})
                    return False
            except ValueError:
                raprint(f"Warning: Could not parse 'expires_at' timestamp '{expires_at_str}' for key ...{api_key[-4:]}. Ignoring expiration.")

        if requested_model:
            premium_models = ["runway", "gpt-image-1", "imagen-3", "imagen-3-5", "grok-3-beta", "o3", "gemini-2.5-pro-exp-03-25t"]
            if requested_model in premium_models or "midjourney" in requested_model:
                if api_key == "sk-hackathon-2025":
                    raprint(f"Hackathon key ...{api_key[-4:]} attempted to access premium model '{requested_model}'. Access denied.")
                    self._send_json_response(403, {
                        "error": {
                            "message": f"The hackathon key does not have access to premium models like '{requested_model}'.",
                            "type": "insufficient_permissions",
                            "code": "hackathon_premium_denied"
                        }
                    })
                    return False
                user_plan = user_info.get("plan", "0")
                pay2go_upgraded = user_info.get("pay2go_upgraded", False)
                
                has_premium_access = (
                    user_plan in ["100m", "unlimited"] or
                    (user_plan == "pay2go" and pay2go_upgraded)
                )
                
                if not has_premium_access:
                    plan_display = f"'{user_plan}'"
                    if user_plan == "pay2go":
                        plan_display += " (not upgraded)"
                    
                    raprint(f"User {user_info.get('username', 'Unknown')} (Key: ...{api_key[-4:]}) attempted to access premium model '{requested_model}' with insufficient plan: {plan_display}")
                    self._send_json_response(403, {
                        "error": {
                            "message": f"Access to model '{requested_model}' requires a 100m, unlimited, or pay2go upgraded plan. Your current plan: {plan_display}",
                            "type": "insufficient_plan",
                            "code": "premium_model_access_denied"
                        }
                    })
                    return False
                
                raprint(f"Premium model access granted for '{requested_model}' to user {user_info.get('username', 'Unknown')} (Plan: {user_plan}{' upgraded' if pay2go_upgraded else ''})")

        user_plan = user_info.get("plan", "0")
        
        if user_plan == "pay2go":
            available_tokens = user_info.get("available_tokens", 0)
            if available_tokens <= 0:
                raprint(f"User {user_info.get('username', 'Unknown')} (Key: ...{api_key[-4:]}) has no available tokens in pay2go plan. Available: {available_tokens}")
                self._send_json_response(429, {
                    "error": {
                        "message": f"You have no available tokens remaining in your pay2go plan. Current balance: {available_tokens} tokens.",
                        "type": "tokens",
                        "code": "insufficient_tokens"
                    }
                })
                return False
        else:
            daily_limit = get_daily_limit_from_plan(user_plan)

            if daily_limit is not None and daily_limit >= 0:
                last_usage_timestamp = user_info.get("last_usage_timestamp")
                daily_tokens_used = user_info.get("daily_tokens_used", 0)

                if is_new_day(last_usage_timestamp):
                    daily_tokens_used = 0

                if daily_tokens_used >= daily_limit:
                     limit_str = f"{daily_limit:,}" if daily_limit > 0 else "0"
                     raprint(f"User {user_info.get('username', 'Unknown')} (Key: ...{api_key[-4:]}) reached or exceeded daily limit of {limit_str} tokens. Used today (before this request): {daily_tokens_used}.")
                     self._send_json_response(429, {
                         "error": {
                             "message": f"You have reached or exceeded your daily token limit of {limit_str} tokens. Limit resets UTC midnight.",
                             "type": "tokens",
                             "code": "daily_limit_exceeded"
                         }
                     })
                     return False

        self.authenticated_api_key = api_key
        self.authenticated_user_info = user_info
        
        if user_plan == "pay2go":
            available_tokens = user_info.get("available_tokens", 0)
            limit_display = f"Available: {available_tokens:,} tokens"
        else:
            daily_limit = get_daily_limit_from_plan(user_plan)
            limit_display = f"{daily_limit:,}" if daily_limit is not None and daily_limit >= 0 else 'Unlimited'
            limit_display = f"Daily Limit: {limit_display}"
            
        raprint(f"Authenticated user: {user_info.get('username', 'Unknown')} (Key: ...{api_key[-4:]}) - Plan: {user_plan} - {limit_display}")
        return True


    def do_GET(self):
        if self._check_ip_blocked():
            return
            

        if self.path == '/admin/keys':
            auth_header = self.headers.get('Authorization')
            provided_api_key = None
            if auth_header and auth_header.startswith('Bearer '):
                provided_api_key = auth_header.split(' ')[1]

            if provided_api_key != ADMIN_API_KEY:
                raprint(f"Admin GET route access denied. Invalid or missing key. Provided key suffix: ...{provided_api_key[-4:] if provided_api_key else 'None'}")
                self._send_json_response(403, {"error": "Forbidden: Invalid admin API key."})
                return

            raprint("Admin GET request received for /admin/keys")
            try:
                global users_config
                with user_config_lock:
                    try:
                        with open(USERS_CONFIG_FILE, 'r') as f:
                            current_users_config = json.load(f)
                        users_config = current_users_config
                        raprint(f"Reloaded {USERS_CONFIG_FILE} inside admin GET lock.")
                    except (FileNotFoundError, json.JSONDecodeError) as e:
                         raprint(f"ERROR reloading user config inside admin GET lock: {e}. Using in-memory data.")
                         current_users_config = users_config

                    users_data = current_users_config.get("users", {})
                self._send_json_response(200, {"users": users_data})
                raprint("Admin: Sent list of all users/keys.")
                return

            except Exception as e:
                raprint(f"Error processing admin GET request: {e}\n{traceback.format_exc()}")
                self._send_json_response(500, {"error": f"Internal server error processing admin GET request: {e}"})
                return

        elif self.path == '/v1/models':
            self._send_json_response(200, {"object": "list", "data": AVAILABLE_MODELS_LIST})
            return

        elif self.path == '/v1/usage':
            auth_header = self.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                api_key = auth_header.split(' ')[1]
                user_data = users_config.get("users", {}).get(api_key)

                if user_data and user_data.get("enabled", False):
                    daily_tokens_used = user_data.get("daily_tokens_used", 0)
                    last_usage_timestamp = user_data.get("last_usage_timestamp")

                    if is_new_day(last_usage_timestamp):
                        daily_tokens_used = 0

                    user_usage_data = {
                        "object": "usage",
                        "username": user_data.get("username", "N/A"),
                        "plan": user_data.get("plan", "N/A"),
                        "total_tokens": user_data.get("total_tokens", 0),
                        "daily_tokens_used": daily_tokens_used,
                        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }
                    
                    if user_data.get("plan") == "pay2go":
                        user_usage_data["available_tokens"] = user_data.get("available_tokens", 0)

                    self._send_json_response(200, user_usage_data)
                    return

            total_tokens_processed = 0
            daily_tokens_processed = 0
            current_users_data = users_config.get("users", {})

            for user_key, user_data in current_users_data.items():
                user_total = user_data.get('total_tokens', 0)
                if isinstance(user_total, int): total_tokens_processed += user_total
                else: raprint(f"Warning: Invalid 'total_tokens' type ({type(user_total)}) for user '{user_data.get('username', user_key)}'.")

                last_usage = user_data.get('last_usage_timestamp')
                if last_usage and not is_new_day(last_usage):
                    user_daily = user_data.get('daily_tokens_used', 0)
                    if isinstance(user_daily, int): daily_tokens_processed += user_daily
                    else: raprint(f"Warning: Invalid 'daily_tokens_used' type ({type(user_daily)}) for user '{user_data.get('username', user_key)}'.")

            usage_data = {
                "total_tokens_processed": total_tokens_processed,
                "daily_tokens_processed_today_utc": daily_tokens_processed,
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            self._send_json_response(200, usage_data)
            return

        elif self.path.startswith('/v1/') and self.path not in ['/v1/models', '/v1/usage']:
             raprint(f"Blocking GET request for undefined authenticated /v1/ path: {self.path}")
             self.send_error(404, "Not Found (Undefined v1 Endpoint)")
             return

        elif self.path == '/' or 'home' in self.path or 'docs' in self.path or 'features' in self.path or 'pricing' in self.path or 'privacy' in self.path or 'terms' in self.path:
            try:
                total_tokens = 0
                if users_config and "users" in users_config:
                    for user_data in users_config.get("users", {}).values():
                        user_tokens = user_data.get('total_tokens', 0)
                        if isinstance(user_tokens, int): total_tokens += user_tokens
                        else: raprint(f"Warning: Invalid 'total_tokens' type ({type(user_tokens)}) for user {user_data.get('username', 'Unknown')}.")

                formatted_total_tokens = f"{total_tokens:,}"
                index_path = os.path.join(STATIC_DIRECTORY, 'index.html')
                with open(index_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                modified_html_content = html_content.replace('<!-- TOTAL_TOKENS -->', formatted_total_tokens)
                encoded_content = modified_html_content.encode('utf-8')

                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded_content)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                try:
                    self.end_headers()
                    self.wfile.write(encoded_content)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    raprint("Client disconnected while serving index.html")
                except Exception as e:
                    raprint(f"Error serving index.html: {e}")
                return
            except FileNotFoundError:
                 index_path_error = os.path.join(STATIC_DIRECTORY, 'index.html')
                 raprint(f"ERROR: index.html not found at {index_path_error}")
                 self.send_error(404, "File Not Found: index.html")
                 return
            except Exception as e:
                raprint(f"Error serving modified index.html: {e}\n{traceback.format_exc()}")
                self.send_error(500, "Internal Server Error serving index.html")
                return

        elif self.path == '/favicon.png':
            try:
                super().do_GET()
            except Exception as e:
                 raprint(f"Error serving static file {self.path}: {e}")
                 self.send_error(500, f"Error serving file: {e}")
            return

        elif self.path == '/chat':
            try:
                chat_page_path = os.path.join(STATIC_DIRECTORY, 'chat.html')
                if not os.path.exists(chat_page_path):
                    placeholder_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat - Coming Soon</title>
    <style>
        body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f0f0f0; color: #333; }
        .container { text-align: center; padding: 20px; background-color: #fff; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1 { color: #007bff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Chat Feature Coming Soon!</h1>
        <p>We're working hard to bring you an amazing chat experience.</p>
        <p>Please check back later.</p>
    </div>
</body>
</html>
"""
                    with open(chat_page_path, 'w', encoding='utf-8') as f_chat:
                        f_chat.write(placeholder_content)
                    raprint(f"INFO: chat.html not found, created a placeholder at {chat_page_path}")
                    html_content = placeholder_content
                else:
                    with open(chat_page_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()

                encoded_content = html_content.encode('utf-8')

                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded_content)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                try:
                    self.end_headers()
                    self.wfile.write(encoded_content)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    raprint("Client disconnected while serving chat.html")
                except Exception as e:
                    raprint(f"Error serving chat.html: {e}")
                return
            except FileNotFoundError:
                 chat_page_path_error = os.path.join(STATIC_DIRECTORY, 'chat.html')
                 raprint(f"ERROR: chat.html still reported as not found at {chat_page_path_error} despite check/creation attempt.")
                 self.send_error(404, "File Not Found: chat.html (Issue creating/finding placeholder)")
                 return
            except Exception as e:
                raprint(f"Error serving chat.html: {e}\n{traceback.format_exc()}")
                self.send_error(500, "Internal Server Error serving chat.html")
                return

        else:
            raprint(f"Blocking GET request for unallowed path: {self.path}")
            self.send_error(404, "Not Found")
            return


    def do_POST(self):
        client_ip = self.get_client_ip()
        if rate_monitor.is_ip_blocked(client_ip):
            pass
            
        if self.path == '/admin/keys':
            auth_header = self.headers.get('Authorization')
            provided_api_key = None
            if auth_header and auth_header.startswith('Bearer '):
                provided_api_key = auth_header.split(' ')[1]

            if provided_api_key != ADMIN_API_KEY:
               raprint(f"Admin route access denied. Invalid or missing key. Provided key suffix: ...{provided_api_key[-4:] if provided_api_key else 'None'}")
               self._send_json_response(403, {"error": "Forbidden: Invalid admin API key."})
               return

            raprint("Admin request received for /admin/keys")
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    self._send_json_response(400, {"error": "Admin request body is missing or empty."})
                    return
                body_bytes = self.rfile.read(content_length)
                body_json = json.loads(body_bytes.decode('utf-8'))

                action = body_json.get('action')
                target_api_key = body_json.get('api_key')

                if not action or not target_api_key:
                    self._send_json_response(400, {"error": "Missing 'action' or 'api_key' in admin request body."})
                    return

                raprint(f"Admin action requested: {action} for key ...{target_api_key[-4:]}")

                global users_config

                with user_config_lock:
                    try:
                        with open(USERS_CONFIG_FILE, 'r') as f:
                            current_users_config = json.load(f)
                        users_config = current_users_config
                        raprint(f"Reloaded {USERS_CONFIG_FILE} inside admin lock.")
                    except (FileNotFoundError, json.JSONDecodeError) as e:
                         raprint(f"ERROR reloading user config inside admin lock: {e}. Using in-memory data.")
                         current_users_config = users_config

                    users_dict = current_users_config.get("users", {})
                    config_changed = False
                    valid_plans = ["0", "500k", "100m", "unlimited", "pay2go"]

                    if action == 'add':
                        username = body_json.get('username')
                        plan = body_json.get('plan', "0")
                        user_id = body_json.get('user_id')
                        if not username:
                            self._send_json_response(400, {"error": "Missing 'username' for 'add' action."})
                            return
                        if plan not in valid_plans:
                             self._send_json_response(400, {"error": f"Invalid plan '{plan}'. Valid plans: {valid_plans}"})
                             return
                        if target_api_key in users_dict:
                            self._send_json_response(409, {"error": f"API key ...{target_api_key[-4:]} already exists."})
                            return

                        new_user_data = {
                            "username": username,
                            "user_id": user_id,
                            "plan": plan,
                            "enabled": True,
                            "total_tokens": 0,
                            "daily_tokens_used": 0,
                            "last_usage_timestamp": None,
                            "last_updated_timestamp": int(time.time())
                        }
                        
                        if plan == "pay2go":
                            new_user_data["available_tokens"] = 0
                            new_user_data["pay2go_upgraded"] = False
                            
                        users_dict[target_api_key] = new_user_data
                        current_users_config["users"] = users_dict
                        config_changed = True
                        raprint(f"Admin: Added user '{username}' (ID: {user_id if user_id else 'N/A'}) with key ...{target_api_key[-4:]} and plan '{plan}'.")
                        self._send_json_response(201, {"message": f"User '{username}' added successfully with key {target_api_key}."})


                    elif action == 'enable' or action == 'disable':
                        user_data = users_dict.get(target_api_key)
                        if not user_data:
                            self._send_json_response(404, {"error": f"API key ...{target_api_key[-4:]} not found."})
                            return

                        new_status = (action == 'enable')
                        if user_data.get('enabled') == new_status:
                             self._send_json_response(200, {"message": f"API key ...{target_api_key[-4:]} is already {action}d."})
                        else:
                            user_data['enabled'] = new_status
                            user_data['last_updated_timestamp'] = int(time.time())
                            config_changed = True
                            raprint(f"Admin: Set key ...{target_api_key[-4:]} enabled status to {new_status}.")
                            self._send_json_response(200, {"message": f"API key ...{target_api_key[-4:]} has been {action}d."})

                    elif action == 'change_plan':
                        user_data = users_dict.get(target_api_key)
                        if not user_data:
                            self._send_json_response(404, {"error": f"API key ...{target_api_key[-4:]} not found."})
                            return

                        new_plan = body_json.get('new_plan')
                        if not new_plan:
                             self._send_json_response(400, {"error": "Missing 'new_plan' parameter for 'change_plan' action."})
                             return
                        if new_plan not in valid_plans:
                             self._send_json_response(400, {"error": f"Invalid plan '{new_plan}'. Valid plans: {valid_plans}"})
                             return

                        old_plan = user_data.get('plan', 'N/A')
                        if old_plan == new_plan:
                             self._send_json_response(200, {"message": f"API key ...{target_api_key[-4:]} already has plan '{new_plan}'."})
                        else:
                            user_data['plan'] = new_plan
                            user_data['last_updated_timestamp'] = int(time.time())
                            
                            if new_plan == 'pay2go' and old_plan != 'pay2go':
                                user_data['available_tokens'] = 0
                                user_data['pay2go_upgraded'] = False
                                raprint(f"Admin: Initialized available_tokens to 0 and pay2go_upgraded to False for new pay2go user.")
                            elif old_plan == 'pay2go' and new_plan != 'pay2go':
                                if 'available_tokens' in user_data:
                                    del user_data['available_tokens']
                                if 'pay2go_upgraded' in user_data:
                                    del user_data['pay2go_upgraded']
                                    raprint(f"Admin: Removed available_tokens and pay2go_upgraded fields when switching from pay2go.")
                            
                            config_changed = True
                            raprint(f"Admin: Changed plan for key ...{target_api_key[-4:]} from '{old_plan}' to '{new_plan}'.")
                            self._send_json_response(200, {"message": f"Plan for API key ...{target_api_key[-4:]} changed from '{old_plan}' to '{new_plan}'."})

                    elif action == 'resetkey':
                        user_data = users_dict.get(target_api_key)
                        if not user_data:
                            self._send_json_response(404, {"error": f"API key ...{target_api_key[-4:]} not found."})
                            return

                        new_key = f"sk-{secrets.token_hex(24)}"

                        while new_key in users_dict:
                            new_key = f"sk-{secrets.token_hex(24)}"

                        users_dict[new_key] = user_data
                        del users_dict[target_api_key]
                        config_changed = True

                        raprint(f"Admin: Reset key for user '{user_data.get('username', 'Unknown')}' (Old: ...{target_api_key[-4:]}). New key starts with ...{new_key[:10]}...")
                        self._send_json_response(200, {"message": f"Key for user '{user_data.get('username', 'Unknown')}' reset successfully.", "new_api_key": new_key})

                    elif action == 'add_tokens':
                        user_data = users_dict.get(target_api_key)
                        if not user_data:
                            self._send_json_response(404, {"error": f"API key ...{target_api_key[-4:]} not found."})
                            return

                        if user_data.get('plan') != 'pay2go':
                            self._send_json_response(400, {"error": f"User ...{target_api_key[-4:]} does not have a pay2go plan. Current plan: {user_data.get('plan', 'Unknown')}"})
                            return

                        tokens_to_add = body_json.get('tokens')
                        if not isinstance(tokens_to_add, int) or tokens_to_add <= 0:
                            self._send_json_response(400, {"error": "Missing or invalid 'tokens' parameter for 'add_tokens' action. Must be a positive integer."})
                            return

                        current_available = user_data.get('available_tokens', 0)
                        new_available = current_available + tokens_to_add
                        user_data['available_tokens'] = new_available
                        user_data['last_updated_timestamp'] = int(time.time())
                        config_changed = True

                        raprint(f"Admin: Added {tokens_to_add:,} tokens to pay2go user '{user_data.get('username', 'Unknown')}' (Key: ...{target_api_key[-4:]}). Balance: {current_available:,} -> {new_available:,}")
                        self._send_json_response(200, {"message": f"Added {tokens_to_add:,} tokens to user '{user_data.get('username', 'Unknown')}'. New balance: {new_available:,} tokens."})

                    elif action == 'upgrade_pay2go':
                        user_data = users_dict.get(target_api_key)
                        if not user_data:
                            self._send_json_response(404, {"error": f"API key ...{target_api_key[-4:]} not found."})
                            return

                        if user_data.get('plan') != 'pay2go':
                            self._send_json_response(400, {"error": f"User ...{target_api_key[-4:]} does not have a pay2go plan. Current plan: {user_data.get('plan', 'Unknown')}"})
                            return

                        upgrade_status = body_json.get('upgraded', True)
                        if not isinstance(upgrade_status, bool):
                            self._send_json_response(400, {"error": "Invalid 'upgraded' parameter for 'upgrade_pay2go' action. Must be true or false."})
                            return

                        current_status = user_data.get('pay2go_upgraded', False)
                        if current_status == upgrade_status:
                            status_text = "upgraded" if upgrade_status else "not upgraded"
                            self._send_json_response(200, {"message": f"User ...{target_api_key[-4:]} is already {status_text}."})
                        else:
                            user_data['pay2go_upgraded'] = upgrade_status
                            user_data['last_updated_timestamp'] = int(time.time())
                            config_changed = True
                            
                            status_text = "upgraded" if upgrade_status else "downgraded"
                            raprint(f"Admin: {status_text.capitalize()} pay2go user '{user_data.get('username', 'Unknown')}' (Key: ...{target_api_key[-4:]}). Premium access: {upgrade_status}")
                            self._send_json_response(200, {"message": f"User '{user_data.get('username', 'Unknown')}' has been {status_text}. Premium model access: {'enabled' if upgrade_status else 'disabled'}."})

                    elif action == 'set_opensource':
                        user_data = users_dict.get(target_api_key)
                        if not user_data:
                            self._send_json_response(404, {"error": f"API key ...{target_api_key[-4:]} not found."})
                            return

                        opensource_access = body_json.get('opensource', False)
                        if not isinstance(opensource_access, bool):
                            self._send_json_response(400, {"error": "Invalid 'opensource' parameter for 'set_opensource' action. Must be true or false."})
                            return

                        current_access = user_data.get('opensource', False)
                        if current_access == opensource_access:
                            status_text = "enabled" if opensource_access else "disabled"
                            self._send_json_response(200, {"message": f"User ...{target_api_key[-4:]} already has opensource access {status_text}."})
                        else:
                            user_data['opensource'] = opensource_access
                            user_data['last_updated_timestamp'] = int(time.time())
                            config_changed = True
                            
                            status_text = "enabled" if opensource_access else "disabled"
                            raprint(f"Admin: {status_text.capitalize()} opensource access for user '{user_data.get('username', 'Unknown')}' (Key: ...{target_api_key[-4:]})")
                            self._send_json_response(200, {"message": f"Opensource access {status_text} for user '{user_data.get('username', 'Unknown')}'."})

                    elif action == 'set_opensource_rpm':
                        user_data = users_dict.get(target_api_key)
                        if not user_data:
                            self._send_json_response(404, {"error": f"API key ...{target_api_key[-4:]} not found."})
                            return

                        rpm_limit = body_json.get('rpm_limit')
                        if not isinstance(rpm_limit, int) or rpm_limit < 0:
                            self._send_json_response(400, {"error": "Invalid 'rpm_limit' parameter for 'set_opensource_rpm' action. Must be a non-negative integer."})
                            return

                        current_rpm = user_data.get('opensource_rpm', 0)
                        if current_rpm == rpm_limit:
                            self._send_json_response(200, {"message": f"User ...{target_api_key[-4:]} already has opensource RPM limit set to {rpm_limit}."})
                        else:
                            user_data['opensource_rpm'] = rpm_limit
                            user_data['last_updated_timestamp'] = int(time.time())
                            config_changed = True
                            
                            raprint(f"Admin: Set opensource RPM limit to {rpm_limit} for user '{user_data.get('username', 'Unknown')}' (Key: ...{target_api_key[-4:]})")
                            self._send_json_response(200, {"message": f"Opensource RPM limit set to {rpm_limit} for user '{user_data.get('username', 'Unknown')}'."})

                    else:
                        self._send_json_response(400, {"error": f"Invalid admin action: {action}. Valid actions: add, enable, disable, change_plan, resetkey, add_tokens, upgrade_pay2go, set_opensource, set_opensource_rpm."})
                        return

                    if config_changed:
                        if not save_users_config_safely(current_users_config):
                             raprint(f"CRITICAL ERROR: Failed to save user config after admin action '{action}' for key ...{target_api_key[-4:]}")
                        else:
                             raprint("Admin changes saved successfully.")
                    else:
                        raprint("No changes made by admin action.")

                return

            except json.JSONDecodeError as e:
                raprint(f"ERROR: Invalid JSON in admin request body. Error: {e}")
                self._send_json_response(400, {"error": "Invalid JSON in admin request body."})
                return
            except Exception as e:
                raprint(f"Error processing admin request: {e}\n{traceback.format_exc()}")
                self._send_json_response(500, {"error": f"Internal server error processing admin request: {e}"})
                return


        raprint(f"Processing regular API POST request for path: {self.path}")

        if not providers_config or "endpoints" not in providers_config:
            api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
            raprint(f"ERROR: Provider configuration is missing or invalid (API Key: {api_key_suffix})")
            self.send_error(500, "Provider configuration is missing or invalid.")
            return

        endpoint_config = providers_config.get("endpoints", {}).get(self.path)
        if not endpoint_config or "models" not in endpoint_config:
            api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
            raprint(f"ERROR: Configuration missing for endpoint: {self.path} (API Key: {api_key_suffix})")
            self._send_json_response(400, {"error": f"Configuration missing for endpoint: {self.path}"})
            return

        is_audio_transcription_path = (self.path == '/v1/audio/transcriptions')
        is_audio_speech_path = (self.path == '/v1/audio/speech')
        is_responses_path = (self.path == '/v1/responses')

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            raprint(f"Content-Length: {content_length}")
            if content_length == 0:
                 api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
                 raprint(f"ERROR: Request body is missing or empty (Content-Length is 0) (API Key: {api_key_suffix})")
                 self._send_json_response(400, {"error": "Request body is missing or empty."})
                 return
            original_body_bytes = self.rfile.read(content_length)
            raprint(f"Raw request body (first 500 bytes): {original_body_bytes[:500]}...")
        except Exception as e:
            api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
            raprint(f"Error reading request body: {e} (API Key: {api_key_suffix})")
            self._send_json_response(500, {"error": f"Internal server error reading request: {e}"})
            return

        body_json = None
        requested_model = None

        if not is_audio_transcription_path:
            try:
                body_json = json.loads(original_body_bytes.decode('utf-8'))
                requested_model = body_json.get('model')
                raprint(f"Requested model (from JSON body): {requested_model}")
                if not requested_model:
                    api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
                    raprint(f"ERROR: Missing 'model' field in JSON request body (API Key: {api_key_suffix})")
                    self._send_json_response(400, {"error": "Missing 'model' field in request body."})
                    return
                
                if 'n' in body_json and self.path == '/v1/chat/completions':
                    raprint(f"INFO: 'n' parameter is not supported and has been removed from the request for model '{requested_model}'.")
                    del body_json['n']
                
                if is_responses_path:
                    if not body_json.get('input'):
                        api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
                        raprint(f"ERROR: Missing 'input' field in /v1/responses request body (API Key: {api_key_suffix})")
                        self._send_json_response(400, {"error": "Missing 'input' field in request body for /v1/responses endpoint."})
                        return
                    raprint(f"v1/responses request - Input: {body_json.get('input')[:100]}{'...' if len(str(body_json.get('input', ''))) > 100 else ''}")
                
            except json.JSONDecodeError as e:
                api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
                raprint(f"ERROR: Invalid JSON in request body. Error: {e} (API Key: {api_key_suffix})")
                raprint(f"Failed body content: {original_body_bytes.decode('utf-8', errors='ignore')}")
                self._send_json_response(400, {"error": "Invalid JSON in request body."})
                return
        else:
            model_keys = list(endpoint_config.get("models", {}).keys())
            if model_keys:
                requested_model = model_keys[0]
                raprint(f"Audio transcription: Using first configured model '{requested_model}' for provider selection.")
            else:
                api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
                raprint(f"ERROR: No models configured for endpoint {self.path} (API Key: {api_key_suffix})")
                self._send_json_response(400, {"error": f"No models configured for endpoint {self.path}"})
                return

        if self.path.startswith('/v1/'):
             if self._check_ip_blocked(requested_model):
                 return
                 
             if not self._authenticate_request(requested_model):
                 return
             
             self._log_api_request(requested_model)

             provider_list_for_model = endpoint_config.get("models", {}).get(requested_model, [])
             is_alpha_model = any(p.get("alpha") for p in provider_list_for_model)
             if is_alpha_model:
                 user_id = self.authenticated_user_info.get("username")
                 if str(user_id) != "1314958804890157109":
                     raprint(f"Access denied for user {user_id} to alpha model {requested_model}")
                     self._send_json_response(403, {
                         "error": {
                             "message": f"You do not have access to the model '{requested_model}'. This is a private alpha model.",
                             "type": "permission_denied",
                             "code": "alpha_model_access_denied"
                         }
                     })
                     return

             if not preauth_tokens(self.authenticated_api_key):
                 raprint(f"Pre-authorization failed for user ...{self.authenticated_api_key[-4:]} - insufficient tokens for 5k reserve")
                 self._send_json_response(429, {
                     "error": {
                         "message": "Insufficient tokens for request pre-authorization. A temporary reserve of 5000 tokens is required.",
                         "type": "tokens",
                         "code": "insufficient_tokens_preauth"
                     }
                 })
                 return
        else:
             self.send_error(404, "Endpoint not found for POST.")
             return

        estimated_input_content_tokens = 0
        if body_json:
            try:
                if is_responses_path and 'input' in body_json and isinstance(body_json['input'], str):
                    total_input_content_length = len(body_json['input'])
                    estimated_input_content_tokens = (total_input_content_length + 3) // 4
                    raprint(f"Estimated input tokens for /v1/responses (from input content / 4): {estimated_input_content_tokens}")
                elif 'messages' in body_json and isinstance(body_json['messages'], list):
                    total_input_content_length = 0
                    for message in body_json['messages']:
                        if isinstance(message, dict) and 'content' in message and isinstance(message['content'], str):
                            total_input_content_length += len(message['content'])
                    estimated_input_content_tokens = (total_input_content_length + 3) // 4
                    raprint(f"Estimated input tokens (from message content / 4): {estimated_input_content_tokens}")
            except Exception as e:
                raprint(f"Error estimating input content tokens: {e}")

        with providers_config_lock:
            providers = endpoint_config["models"].get(requested_model)
            if not providers:
                api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
                raprint(f"ERROR: Model not found: {requested_model} at endpoint {self.path}. Returning 404. (API Key: {api_key_suffix})")
                error_payload = {
                    "error": {
                        "code": "model_not_found",
                        "message": f"The model `{requested_model}` does not exist or you do not have access to it.",
                        "param": None,
                        "type": "invalid_request_error"
                    }
                }
                self._send_json_response(404, error_payload)
                return

        grouped_by_priority = {}
        for p in providers:
            priority = p.get('priority', 99)
            if priority not in grouped_by_priority:
                grouped_by_priority[priority] = {}
            
            base_url = p.get('base_url')
            if base_url not in grouped_by_priority[priority]:
                grouped_by_priority[priority][base_url] = []
            grouped_by_priority[priority][base_url].append(p)

        shuffled_providers = []
        for priority in sorted(grouped_by_priority.keys()):
            for base_url in grouped_by_priority[priority]:
                group = grouped_by_priority[priority][base_url]
                random.shuffle(group)
                shuffled_providers.extend(group)
        
        last_error = None
        last_error_body = None
        for provider in shuffled_providers:
            provider_name = provider.get('provider_name', 'Unknown')
            base_url = provider.get('base_url')
            api_key = provider.get('api_key')
            model = provider.get('model')

            if not base_url or not api_key:
                raprint(f"Skipping provider {provider_name}: Missing base_url or api_key.")
                last_error = f"Configuration error for provider {provider_name}"
                continue

            target_url = base_url.rstrip('/') + self.path
            raprint(f"Attempting request to {provider_name} ({target_url}) for model {requested_model} (Provider model: {model})...")

            body_to_send_to_provider = original_body_bytes

            if not is_audio_transcription_path:
                if body_json:
                    temp_body_dict = body_json.copy()
                    temp_body_dict['model'] = model
                    body_to_send_to_provider = json.dumps(temp_body_dict).encode('utf-8')
                else:
                    raprint(f"Warning: body_json not available for non-transcription path {self.path}. Trying to re-parse original_body_bytes.")
                    try:
                        temp_body_dict = json.loads(original_body_bytes.decode('utf-8'))
                        temp_body_dict['model'] = model
                        body_to_send_to_provider = json.dumps(temp_body_dict).encode('utf-8')
                    except json.JSONDecodeError:
                        raprint(f"Error: Could not re-parse original_body_bytes as JSON for provider {provider_name}. Sending original body.")

            try:
                headers = {
                    'User-Agent': 'curl/7.68.0',
                    'Accept': '*/*',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'close'
                }
                provider_request = urllib.request.Request(target_url, data=body_to_send_to_provider, method='POST', headers=headers)
                client_content_type = self.headers.get('Content-Type')
                if client_content_type:
                    provider_request.add_header('Content-Type', client_content_type)
                else:
                    raprint(f"Warning: Client did not send Content-Type header for {self.path}. Provider might reject.")
                if "/api/openai" not in base_url:
                    provider_request.add_header('Authorization', f'Bearer {api_key}')
                else:
                    raprint(f"INFO: Omitting Authorization header for OpenAI-compatible endpoint: {base_url}")


                with urllib.request.urlopen(provider_request) as response:
                    update_provider_failure_count(self.path, requested_model, provider, increment=False)
                    user_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') and isinstance(self.authenticated_api_key, str) else "No-Auth"
                    print(f"Provider {provider_name} succeeded with status {response.status}")
                    raprint(f"Success from {provider_name} ({response.status}) - User: {user_key_suffix}")
                    response_status = response.status
                    response_headers_dict = dict(response.getheaders())
                    content_type = response_headers_dict.get('Content-Type', '').lower()

                    is_streaming = 'text/event-stream' in content_type

                    if is_streaming:
                        raprint(f"Detected streaming response (Content-Type: {content_type}). Processing as SSE.")
                        self.send_response(response_status)
                        for header, value in response_headers_dict.items():
                            if header.lower() not in ['transfer-encoding', 'connection', 'content-encoding', 'content-length', 'access-control-allow-origin']:
                                self.send_header(header, value)
                        self.end_headers()

                        streamed_content_length = 0
                        response_buffer = io.BytesIO()
                        sse_line_buffer = b""

                        try:
                            while True:
                                byte_chunk = response.read(1)
                                if not byte_chunk:
                                    break

                                try:
                                    self.wfile.write(byte_chunk)
                                    self.wfile.flush()
                                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                                    raprint("Client disconnected during streaming")
                                    break
                                
                                response_buffer.write(byte_chunk)
                                sse_line_buffer += byte_chunk
                                
                                while b'\n' in sse_line_buffer:
                                    line_end = sse_line_buffer.find(b'\n')
                                    line = sse_line_buffer[:line_end].strip()
                                    sse_line_buffer = sse_line_buffer[line_end + 1:]
                                    
                                    if line.startswith(b'data:'):
                                        data_str = line[len(b'data:'):].strip().decode('utf-8', errors='ignore')
                                        if data_str and data_str != '[DONE]':
                                            try:
                                                event_data = json.loads(data_str)
                                                if isinstance(event_data, dict):
                                                    choices = event_data.get('choices')
                                                    if isinstance(choices, list):
                                                        for choice in choices:
                                                            if isinstance(choice, dict):
                                                                delta = choice.get('delta')
                                                                if isinstance(delta, dict):
                                                                    content = delta.get('content')
                                                                    if isinstance(content, str):
                                                                        streamed_content_length += len(content)
                                            except json.JSONDecodeError:
                                                pass
                                            except Exception as e:
                                                raprint(f"Warning: Error processing SSE data for content length: {e}")
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            raprint("Client disconnected during streaming response")
                        except Exception as e:
                            raprint(f"Error during streaming: {e}")

                        raprint(f"Finished streaming response from {provider_name}.")
                        response_body_bytes = response_buffer.getvalue()

                    else:
                        raprint(f"Detected non-streaming response (Content-Type: {content_type}). Reading full body.")
                        response_body_bytes = response.read()

                        self.send_response(response_status)
                        for header, value in response_headers_dict.items():
                            if header.lower() == 'content-length':
                                self.send_header('Content-Length', str(len(response_body_bytes)))
                            elif header.lower() not in ['transfer-encoding', 'connection', 'access-control-allow-origin']:
                                self.send_header(header, value)
                        if 'Content-Length' not in response_headers_dict:
                             self.send_header('Content-Length', str(len(response_body_bytes)))

                        self.end_headers()

                        try:
                            self.wfile.write(response_body_bytes)
                            self.wfile.flush()
                            raprint(f"Sent complete non-streaming response from {provider_name}.")
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            raprint("Client disconnected during non-streaming response")
                        except Exception as e:
                            raprint(f"Error sending non-streaming response: {e}")

                    tokens_used = 0
                    explicit_tokens_found = False

                    is_image_generation_request = (self.path == '/v1/images/generations')
                    is_current_path_audio_transcription = (self.path == '/v1/audio/transcriptions')
                    is_current_path_audio_speech = (self.path == '/v1/audio/speech')
                    is_current_path_responses = (self.path == '/v1/responses')

                    if is_image_generation_request and response_status < 400:
                        tokens_used = 1
                        explicit_tokens_found = True
                        raprint(f"Image generation request ({self.path}): Base tokens set to 1.")
                    elif is_current_path_responses and response_status < 400:
                        parsed_response_json_for_tokens = None
                        try:
                            response_text = ""
                            if response_body_bytes.startswith(b'\x1f\x8b'):
                                import gzip
                                try:
                                    decompressed_data = gzip.decompress(response_body_bytes)
                                    response_text = decompressed_data.decode('utf-8')
                                    print(f"🚨 V1/RESPONSES TOKEN PARSING: Decompressed gzip response")
                                except Exception as decomp_error:
                                    print(f"🚨 V1/RESPONSES TOKEN PARSING ERROR: Failed to decompress gzip: {decomp_error}")
                                    response_text = response_body_bytes.decode('utf-8', errors='replace')
                            else:
                                response_text = response_body_bytes.decode('utf-8')
                            
                            parsed_response_json_for_tokens = json.loads(response_text)
                            print(f"🚨 V1/RESPONSES TOKEN PARSING: Full response structure: {json.dumps(parsed_response_json_for_tokens, indent=2)}")
                        except Exception as e:
                            print(f"🚨 V1/RESPONSES TOKEN PARSING ERROR: Failed to parse JSON: {e}")

                        if parsed_response_json_for_tokens and \
                           isinstance(parsed_response_json_for_tokens.get('usage'), dict) and \
                           isinstance(parsed_response_json_for_tokens['usage'].get('total_tokens'), int):
                            tokens_used = parsed_response_json_for_tokens['usage']['total_tokens']
                            explicit_tokens_found = True
                            raprint(f"v1/responses: Extracted 'usage.total_tokens': {tokens_used}")
                            print(f"🚨 V1/RESPONSES TOKEN PARSING: Successfully extracted tokens from usage field: {tokens_used}")
                        else:
                            extracted_text = ""
                            if parsed_response_json_for_tokens and isinstance(parsed_response_json_for_tokens.get('output'), list):
                                for output_item in parsed_response_json_for_tokens['output']:
                                    if isinstance(output_item, dict) and output_item.get('type') == 'message':
                                        content_array = output_item.get('content', [])
                                        if isinstance(content_array, list):
                                            for content_item in content_array:
                                                if isinstance(content_item, dict) and content_item.get('type') == 'output_text':
                                                    text_content = content_item.get('text', '')
                                                    if isinstance(text_content, str):
                                                        extracted_text += text_content
                            
                            if extracted_text:
                                output_text_tokens = (len(extracted_text) + 3) // 4
                                input_tokens_estimate = estimated_input_content_tokens if 'estimated_input_content_tokens' in locals() else 0
                                tokens_used = input_tokens_estimate + output_text_tokens
                                if tokens_used == 0 and len(extracted_text) > 0:
                                    tokens_used = 1
                                explicit_tokens_found = False
                                raprint(f"v1/responses: Estimated tokens from extracted text length + input: {input_tokens_estimate} + {output_text_tokens} = {tokens_used}")
                                print(f"🚨 V1/RESPONSES TOKEN PARSING: Estimated tokens from new format - extracted text length: {len(extracted_text)}, total tokens: {tokens_used}")
                            elif parsed_response_json_for_tokens and isinstance(parsed_response_json_for_tokens.get('output_text'), str):
                                output_text_tokens = (len(parsed_response_json_for_tokens['output_text']) + 3) // 4
                                input_tokens_estimate = estimated_input_content_tokens if 'estimated_input_content_tokens' in locals() else 0
                                tokens_used = input_tokens_estimate + output_text_tokens
                                if tokens_used == 0 and len(parsed_response_json_for_tokens['output_text']) > 0:
                                    tokens_used = 1
                                explicit_tokens_found = False
                                raprint(f"v1/responses: Estimated tokens from legacy output_text length + input: {input_tokens_estimate} + {output_text_tokens} = {tokens_used}")
                                print(f"🚨 V1/RESPONSES TOKEN PARSING: Used legacy output_text field, total tokens: {tokens_used}")
                            else:
                                tokens_used = 1
                                explicit_tokens_found = True
                                raprint(f"v1/responses: Base tokens set to 1 (fallback).")
                                print(f"🚨 V1/RESPONSES TOKEN PARSING: No extractable text found, using fallback of 1 token")
                    elif is_current_path_audio_transcription and response_status < 400:
                        parsed_response_json_for_tokens = None
                        try:
                            parsed_response_json_for_tokens = json.loads(response_body_bytes.decode('utf-8'))
                        except:
                            pass

                        if parsed_response_json_for_tokens and \
                           isinstance(parsed_response_json_for_tokens.get('usage'), dict) and \
                           isinstance(parsed_response_json_for_tokens['usage'].get('total_tokens'), int):
                            tokens_used = parsed_response_json_for_tokens['usage']['total_tokens']
                            explicit_tokens_found = True
                            raprint(f"Audio transcription: Extracted 'usage.total_tokens': {tokens_used}")
                        elif parsed_response_json_for_tokens and isinstance(parsed_response_json_for_tokens.get('text'), str):
                            tokens_used = (len(parsed_response_json_for_tokens['text']) + 3) // 4
                            if tokens_used == 0 and len(parsed_response_json_for_tokens['text']) > 0: tokens_used = 1
                            explicit_tokens_found = False
                            raprint(f"Audio transcription: Estimated tokens from output text length: {tokens_used}")
                        else:
                            tokens_used = 1
                            explicit_tokens_found = True
                            raprint(f"Audio transcription: Base tokens set to 1 (fallback).")
                    elif is_current_path_audio_speech and response_status < 400:
                        if body_json and 'input' in body_json and isinstance(body_json['input'], str):
                            input_chars = len(body_json['input'])
                            tokens_used = input_chars
                            if tokens_used == 0: tokens_used = 1
                            explicit_tokens_found = True
                            raprint(f"Audio speech: Base tokens from input characters: {tokens_used}.")
                        else:
                            tokens_used = 1
                            explicit_tokens_found = True
                            raprint(f"Audio speech: Base tokens set to 1 (fallback).")
                    else:
                        trimmed_body = response_body_bytes.strip()
                        is_potential_json = (trimmed_body.startswith(b'{') and trimmed_body.endswith(b'}')) or \
                                            (trimmed_body.startswith(b'[') and trimmed_body.endswith(b']'))

                        if is_potential_json:
                            try:
                                response_json = json.loads(response_body_bytes.decode('utf-8'))
                                if isinstance(response_json, dict) and 'usage' in response_json and isinstance(response_json['usage'], dict) and 'total_tokens' in response_json['usage']:
                                    json_tokens = response_json['usage']['total_tokens']
                                    if isinstance(json_tokens, int) and json_tokens > 0:
                                        tokens_used = json_tokens
                                        raprint(f"Extracted 'usage.total_tokens' (Chat) from JSON: {tokens_used}")
                                        explicit_tokens_found = True
                                    else:
                                        raprint(f"Found 'usage' field but 'total_tokens' is invalid/zero ({json_tokens}).")
                                elif isinstance(response_json, dict) and 'usage' in response_json and isinstance(response_json['usage'], dict) and 'prompt_tokens' in response_json['usage'] and 'completion_tokens' in response_json['usage']:
                                    prompt_tokens = response_json['usage'].get('prompt_tokens', 0)
                                    completion_tokens = response_json['usage'].get('completion_tokens', 0)
                                    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int) and (prompt_tokens > 0 or completion_tokens > 0):
                                         tokens_used = prompt_tokens + completion_tokens
                                         raprint(f"Extracted 'usage.prompt/completion_tokens' (Legacy) from JSON: {prompt_tokens} + {completion_tokens} = {tokens_used}")
                                         explicit_tokens_found = True
                                    else:
                                         raprint(f"Found Legacy usage field but tokens are invalid/zero (P:{prompt_tokens}, C:{completion_tokens}).")
                                elif isinstance(response_json, dict) and 'usage' in response_json and isinstance(response_json['usage'], dict) and 'total_tokens' in response_json['usage']:
                                    embedding_tokens = response_json['usage']['total_tokens']
                                    if isinstance(embedding_tokens, int) and embedding_tokens > 0:
                                         tokens_used = embedding_tokens
                                         raprint(f"Extracted 'usage.total_tokens' (Embeddings) from JSON: {tokens_used}")
                                         explicit_tokens_found = True
                                    else:
                                        raprint(f"Found Embeddings usage field but 'total_tokens' is invalid/zero ({embedding_tokens}).")
                                else:
                                    raprint("No standard token usage information found in the JSON response. Will use fallback estimation.")
                            except json.JSONDecodeError:
                                raprint("Warning: Full response could not be parsed as a single JSON object. Will use fallback estimation.")
                            except Exception as e:
                                raprint(f"Error processing full response as JSON for token counting: {e}. Will use fallback estimation.")


                        if not explicit_tokens_found:
                            raprint("Explicit token usage not found or invalid in full response JSON, applying fallback estimation.")

                            estimated_output_body_tokens = (len(response_body_bytes) + 3) // 4
                            raprint(f"Estimating output tokens based on full response body length ({len(response_body_bytes)} bytes / 4): {estimated_output_body_tokens}")

                            input_tokens_estimate = estimated_input_content_tokens if 'estimated_input_content_tokens' in locals() else 0
                            if 'estimated_input_content_tokens' not in locals():
                                 raprint("Warning: estimated_input_content_tokens not found, using 0 for input estimate.")

                            total_estimated_tokens = input_tokens_estimate + estimated_output_body_tokens
                            raprint(f"Total estimated fallback tokens: {input_tokens_estimate} (input content) + {estimated_output_body_tokens} (output body) = {total_estimated_tokens}")
                            tokens_used = total_estimated_tokens

                    if isinstance(tokens_used, int) and tokens_used > 0:
                         if hasattr(self, 'authenticated_api_key'):
                             log_prefix = "explicit" if explicit_tokens_found else "estimated fallback"
                             provider_multiplier = provider.get('token_multiplier', 1.0)
                             
                             if requested_model in OPENSOURCE_MODELS:
                                 user_has_opensource = self.authenticated_user_info.get("opensource", False) if hasattr(self, 'authenticated_user_info') else False
                                 if user_has_opensource:
                                     raprint(f"Opensource model '{requested_model}' with opensource access: Redirecting token usage to sk-test key")
                                     raprint(f"Attempting to update token count: Raw Tokens={tokens_used} ({log_prefix}), Multiplier={provider_multiplier} for sk-test (user: ...{self.authenticated_api_key[-4:]})")
                                     update_user_token_count(OPENSOURCE_SK_TEST_KEY, tokens_used, provider_multiplier)
                                 else:
                                     raprint(f"Opensource model '{requested_model}' without opensource access: Charging user's own tokens")
                                     raprint(f"Attempting to update token count: Raw Tokens={tokens_used} ({log_prefix}), Multiplier={provider_multiplier} for key ...{self.authenticated_api_key[-4:]}")
                                     update_user_token_count(self.authenticated_api_key, tokens_used, provider_multiplier)
                             else:
                                 raprint(f"Attempting to update token count: Raw Tokens={tokens_used} ({log_prefix}), Multiplier={provider_multiplier} for key ...{self.authenticated_api_key[-4:]}")
                                 update_user_token_count(self.authenticated_api_key, tokens_used, provider_multiplier)
                         else:
                             raprint(f"Warning: Tokens ({tokens_used}) calculated, but authenticated_api_key missing. Cannot update count.")
                    elif explicit_tokens_found:
                         raprint(f"Explicit token usage found but value ({tokens_used}) is invalid. Skipping token count update.")
                    else:
                         raprint(f"No explicit tokens found and fallback estimation resulted in 0 tokens. Skipping token count update.")

                    return

            except urllib.error.HTTPError as e:
                user_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') and isinstance(self.authenticated_api_key, str) else "No-Auth"
                print(f"Provider {provider_name} failed with HTTPError: {e.code} {e.reason}")
                raprint(f"HTTPError from {provider_name}: {e.code} {e.reason} - User: {user_key_suffix}")
                last_error = f"Provider {provider_name} failed with status {e.code}"
                try:
                    error_body = e.read()
                    last_error_body = error_body
                    raprint(f"Error body (bytes): {error_body[:500]}... - User: {user_key_suffix}")
                except Exception as read_err:
                     raprint(f"Could not read error body from {provider_name}: {read_err} - User: {user_key_suffix}")

                raprint(f"Provider {provider_name} returned HTTP error {e.code}. Incrementing failure count.")
                update_provider_failure_count(self.path, requested_model, provider, increment=True)
            except urllib.error.URLError as e:
                user_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') and isinstance(self.authenticated_api_key, str) else "No-Auth"
                print(f"Provider {provider_name} failed with URLError: {e.reason}")
                raprint(f"URLError from {provider_name}: {e.reason} - User: {user_key_suffix}")
                last_error = f"Network error contacting provider {provider_name}: {e.reason}"
                raprint(f"Provider {provider_name} returned URLError. Incrementing failure count.")
                update_provider_failure_count(self.path, requested_model, provider, increment=True)
            except Exception as e:
                user_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') and isinstance(self.authenticated_api_key, str) else "No-Auth"
                print(f"Provider {provider_name} failed with an unexpected error: {e}")
                raprint(f"Unexpected error contacting {provider_name}: {e} - User: {user_key_suffix}")
                raprint(traceback.format_exc())
                last_error = f"Unexpected error with provider {provider_name}: {e}"
                raprint(f"Provider {provider_name} returned unexpected error. Incrementing failure count.")
                update_provider_failure_count(self.path, requested_model, provider, increment=True)


        api_key_suffix = f"...{self.authenticated_api_key[-4:]}" if hasattr(self, 'authenticated_api_key') else "None"
        raprint(f"All providers failed for API Key: {api_key_suffix}")
        
        if hasattr(self, 'authenticated_api_key'):
            refund_preauth_tokens(self.authenticated_api_key)
        
        response_payload = {
            "error": "All upstream providers failed",
            "details": "Unknown error"
        }
        if last_error_body:
            try:
                decoded_body = last_error_body.decode('utf-8')
                response_payload["last_provider_error_body"] = json.loads(decoded_body)
                raprint("Included last provider error body as JSON.")
            except (UnicodeDecodeError, json.JSONDecodeError):
                response_payload["last_provider_error_body"] = last_error_body.decode('utf-8', errors='replace')
                raprint("Included last provider error body as raw string.")

        self._send_json_response(400, response_payload)

    def do_OPTIONS(self):
        self.send_response(204)

        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Max-Age', '86400')

        requested_headers = self.headers.get('Access-Control-Request-Headers')
        if requested_headers:
            self.send_header('Access-Control-Allow-Headers', requested_headers)

        self.end_headers()

if __name__ == "__main__":
    raprint(f"INFO: Server starting without auto-reload.")

    raprint("\n----- Loading Configuration -----")
    providers_config, users_config = load_configurations()

    raprint("\n----- Setting up Special Keys -----")
    setup_hackathon_key()
    raprint("Finished special key setup.")

    try:
        socketserver.TCPServer.allow_reuse_address = True
        class UltraHighPerformanceTCPServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
            request_queue_size = 16384
            
            def __init__(self, *args, **kwargs):
                import concurrent.futures
                self._thread_pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=5000,
                    thread_name_prefix="HTTP"
                )
                
                super().__init__(*args, **kwargs)
                
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, 'SO_REUSEPORT'):
                    try:
                        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except OSError:
                        pass
                
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                
                try:
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
                except OSError:
                    pass
                
                try:
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 0)
                except OSError:
                    pass
            
            def process_request(self, request, client_address):
                """Ultra-fast request processing with thread pool."""
                try:
                    self._thread_pool.submit(self._handle_request_fast, request, client_address)
                except Exception:
                    try:
                        self._handle_request_fast(request, client_address)
                    except:
                        pass
            
            def _handle_request_fast(self, request, client_address):
                """Minimal error handling for maximum speed."""
                try:
                    self.finish_request(request, client_address)
                except:
                    pass
                finally:
                    try:
                        self.shutdown_request(request)
                    except:
                        pass
            
            def shutdown(self):
                """Fast shutdown."""
                try:
                    self._thread_pool.shutdown(wait=False)
                except:
                    pass
                super().shutdown()
        
        with UltraHighPerformanceTCPServer((HOST, PORT), HighPerformanceProxyHandler) as httpd:
             server_address = httpd.server_address
             if len(server_address) == 2:
                 actual_host, actual_port = server_address
             else:
                 actual_host, actual_port = server_address[0], server_address[1]
             display_host = 'localhost' if actual_host == '0.0.0.0' else actual_host

             raprint(f"\nServing HTTP on {actual_host} port {actual_port} (http://{display_host}:{actual_port}/)")
             raprint(f"Serving static files from directory: {STATIC_DIRECTORY}")
             raprint(f"Proxying API requests based on '{CONFIG_FILE}'...")
             if users_config and users_config.get("users"):
                 raprint(f"API Key authentication enabled using '{USERS_CONFIG_FILE}'.")
             else:
                 raprint(f"API Key authentication DISABLED (check '{USERS_CONFIG_FILE}' loading status).")

             httpd.serve_forever()

    except KeyboardInterrupt:
         raprint("\nCtrl+C received. Stopping server permanently.")
    except OSError as e:
        if e.errno == 98:
             raprint(f"ERROR: Port {PORT} is already in use. Waiting a moment...")
             time.sleep(5)
             raprint("Retrying server start...")
        else:
             raprint(f"\nServer runtime error: {e}")
             raprint(traceback.format_exc())
             raprint("Stopping server due to error.")
    except Exception as e:
        raprint(f"\nUnexpected server error: {e}")
        raprint(traceback.format_exc())
        raprint("Stopping server due to unexpected error.")

    raprint("\nServer has stopped.")

