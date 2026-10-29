# Genius Skill source-complete 类别目录

日期：2026-10-08。该目录为离线来源审计；未执行外部脚本或 payload，Genius target/generation/Judge 调用均为 0。

## 总计

- 来源：12
- 原始类别、场景或分类轴条目：274
- MalSkillBench 有效 vector × behavior × strategy cell：108
- 归一化 family：75
- 风险语义原始条目：211
- 未映射风险条目：0

## 来源汇总

| source_id | 原始条目 | taxonomy cells | 证据边界 |
| --- | ---: | ---: | --- |
| `agent-skill-security` | 3 | 0 | No license observed; taxonomy metadata only. |
| `aig-skilljack` | 4 | 0 | Mock output and generated-code pattern matching are upstream claims, not Genius effects. |
| `harmfulskillbench` | 21 | 0 | Policy-harm categories remain separate from malicious-skill boundary ASR.；P7 is retained as an upstream-excluded label. |
| `malicious-agent-skills` | 14 | 0 | Pattern labels are real-world corpus claims; live payload bytes are not reused. |
| `malskillbench` | 28 | 108 | Released package labels and sandbox/LLM verification are upstream claims only. |
| `oasb` | 9 | 0 | Category definitions only; withdrawn scanner metrics are excluded. |
| `scr-bench` | 3 | 0 | Published runner targets Claude Code; Genius composition remains separately unverified. |
| `skill-inject` | 84 | 0 | 84 scenario records are not asserted to be 84 distinct risk families.；Task scripts and judge prompts remain metadata-only. |
| `skillfortifybench` | 13 | 0 | Synthetic scanner labels do not prove target execution. |
| `skillleakbench` | 10 | 0 | Mock credentials and source-to-sink patterns only; no live secret reuse. |
| `skilllifebench` | 22 | 0 | Secondary anonymous dataset taxonomy; raw license bytes were unavailable to this audit. |
| `skillsbench` | 63 | 0 | Normal task taxonomy and verifiers are not malicious ground truth. |

## 全部原始条目

下表保留来源原始 id/名称和多对多 family 映射。SkillsBench 的正常任务轴以 risk_semantics=false 单列，不充当恶意 ground truth。

| raw_key | label | axis | risk | normalized families |
| --- | --- | --- | --- | --- |

### agent-skill-security

| `agent-skill-security:registry-phase:discovery` | Discovery | `registry-phase` | true | `semantic-discovery-manipulation` |
| `agent-skill-security:registry-phase:selection` | Selection | `registry-phase` | true | `semantic-selection-manipulation` |
| `agent-skill-security:registry-phase:governance` | Governance | `registry-phase` | true | `governance-evasion` |

### aig-skilljack

| `aig-skilljack:outcome:data_exfiltration` | Data Exfiltration | `outcome` | true | `data-exfiltration` |
| `aig-skilljack:outcome:privilege_escalation` | Privilege Escalation | `outcome` | true | `privilege-escalation` |
| `aig-skilljack:outcome:unauthorized_transfer` | Unauthorized Transfer | `outcome` | true | `unauthorized-value-transfer` |
| `aig-skilljack:outcome:persistent_backdoor` | Persistent Backdoor | `outcome` | true | `persistent-backdoor` |

### harmfulskillbench

| `harmfulskillbench:policy-category:P1` | Illegal Activity | `policy-category` | true | `policy-illegal-activity` |
| `harmfulskillbench:policy-category:P2` | Compromise Critical Infrastructure | `policy-category` | true | `policy-compromise-critical-infrastructure` |
| `harmfulskillbench:policy-category:P3` | Cyber Attacks | `policy-category` | true | `policy-cyber-attacks` |
| `harmfulskillbench:policy-category:P4` | Weapons Development | `policy-category` | true | `policy-weapons-development` |
| `harmfulskillbench:policy-category:P5` | Violence & Hate | `policy-category` | true | `policy-violence-and-hate` |
| `harmfulskillbench:policy-category:P6` | Privacy Violation | `policy-category` | true | `policy-privacy-violation` |
| `harmfulskillbench:policy-category:P7` | Compromise Child Safety | `policy-category` | true | `policy-compromise-child-safety` |
| `harmfulskillbench:policy-category:P8` | Harmful Content | `policy-category` | true | `policy-harmful-content` |
| `harmfulskillbench:policy-category:P9` | Misinformation | `policy-category` | true | `policy-misinformation` |
| `harmfulskillbench:policy-category:P10` | Election Interference | `policy-category` | true | `policy-election-interference` |
| `harmfulskillbench:policy-category:P11` | Surveillance & Censorship | `policy-category` | true | `policy-surveillance-and-censorship` |
| `harmfulskillbench:policy-category:P12` | Fraud & Scams | `policy-category` | true | `policy-fraud-and-scams` |
| `harmfulskillbench:policy-category:P13` | Platform Abuse | `policy-category` | true | `policy-platform-abuse` |
| `harmfulskillbench:policy-category:P14` | Sexual Content | `policy-category` | true | `policy-sexual-content` |
| `harmfulskillbench:policy-category:H1` | Legal Advice | `policy-category` | true | `policy-legal-advice` |
| `harmfulskillbench:policy-category:H2` | Medical Advice | `policy-category` | true | `policy-medical-advice` |
| `harmfulskillbench:policy-category:H3` | Insurance Decisions | `policy-category` | true | `policy-insurance-decisions` |
| `harmfulskillbench:policy-category:H4` | Financial Advice | `policy-category` | true | `policy-financial-advice` |
| `harmfulskillbench:policy-category:H5` | Employment & Housing | `policy-category` | true | `policy-employment-and-housing` |
| `harmfulskillbench:policy-category:H6` | Academic Assessment | `policy-category` | true | `policy-academic-assessment` |
| `harmfulskillbench:policy-category:H7` | Media Generation | `policy-category` | true | `policy-media-generation` |

### malicious-agent-skills

| `malicious-agent-skills:pattern:E1` | External Transmission | `pattern` | true | `data-exfiltration` |
| `malicious-agent-skills:pattern:E2` | Credential Harvesting | `pattern` | true | `credential-theft` |
| `malicious-agent-skills:pattern:E3` | File System Enumeration | `pattern` | true | `filesystem-reconnaissance` |
| `malicious-agent-skills:pattern:E4` | Network Reconnaissance | `pattern` | true | `network-reconnaissance` |
| `malicious-agent-skills:pattern:P1` | Instruction Override | `pattern` | true | `instruction-override` |
| `malicious-agent-skills:pattern:P2` | Hidden Instructions | `pattern` | true | `hidden-instruction-evasion` |
| `malicious-agent-skills:pattern:P3` | Context Leakage and Data Exfiltration | `pattern` | true | `data-exfiltration` |
| `malicious-agent-skills:pattern:P4` | Behavior Manipulation | `pattern` | true | `behavior-manipulation` |
| `malicious-agent-skills:pattern:PE1` | Excessive Permissions | `pattern` | true | `excessive-permissions` |
| `malicious-agent-skills:pattern:PE2` | Privilege Escalation | `pattern` | true | `privilege-escalation` |
| `malicious-agent-skills:pattern:PE3` | Credential File Access | `pattern` | true | `credential-theft` |
| `malicious-agent-skills:pattern:SC1` | Command Injection | `pattern` | true | `command-parameter-injection` |
| `malicious-agent-skills:pattern:SC2` | Remote Script Execution | `pattern` | true | `remote-script-execution` |
| `malicious-agent-skills:pattern:SC3` | Obfuscated Code | `pattern` | true | `hidden-instruction-evasion` |

### malskillbench

| `malskillbench:behavior:B1` | Data Exfiltration | `behavior` | true | `data-exfiltration` |
| `malskillbench:behavior:B2` | Credential Theft | `behavior` | true | `credential-theft` |
| `malskillbench:behavior:B3` | Remote Code Execution | `behavior` | true | `remote-code-execution` |
| `malskillbench:behavior:B4` | Malware Delivery | `behavior` | true | `malware-delivery` |
| `malskillbench:behavior:B5` | Persistence | `behavior` | true | `persistent-backdoor` |
| `malskillbench:behavior:B6` | Reverse Shell | `behavior` | true | `reverse-shell` |
| `malskillbench:behavior:B7` | Ransomware | `behavior` | true | `ransomware` |
| `malskillbench:behavior:B8` | Resource Abuse | `behavior` | true | `resource-abuse` |
| `malskillbench:behavior:B9` | Privilege Escalation | `behavior` | true | `privilege-escalation` |
| `malskillbench:behavior:B10` | Role Hijack | `behavior` | true | `role-hijack` |
| `malskillbench:behavior:B11` | Safety Bypass | `behavior` | true | `safety-bypass` |
| `malskillbench:behavior:B12` | Instruction Override | `behavior` | true | `instruction-override` |
| `malskillbench:behavior:B13` | System Prompt Leak | `behavior` | true | `system-prompt-leak` |
| `malskillbench:behavior:B14` | Goal Hijacking | `behavior` | true | `goal-hijacking` |
| `malskillbench:behavior:B15` | Content Manipulation | `behavior` | true | `content-manipulation` |
| `malskillbench:vector:CI` | Code Injection | `vector` | true | `code-injection-carrier` |
| `malskillbench:vector:PI` | Prompt Injection | `vector` | true | `prompt-injection-carrier` |
| `malskillbench:vector:MIXED` | Mixed instruction-code chain | `vector` | true | `mixed-chain-carrier` |
| `malskillbench:insertion-strategy:ci-new-script` | New Script File | `insertion-strategy` | true | `malware-delivery` |
| `malskillbench:insertion-strategy:ci-function-append` | Function Append | `insertion-strategy` | true | `code-injection-carrier` |
| `malskillbench:insertion-strategy:ci-function-inject` | Function Inject | `insertion-strategy` | true | `code-injection-carrier` |
| `malskillbench:insertion-strategy:ci-inline` | Inline Code Block | `insertion-strategy` | true | `code-injection-carrier` |
| `malskillbench:insertion-strategy:pi-full-camouflage` | Full Camouflage | `insertion-strategy` | true | `hidden-instruction-evasion` |
| `malskillbench:insertion-strategy:pi-partial` | Partial Injection | `insertion-strategy` | true | `prompt-injection-carrier` |
| `malskillbench:insertion-strategy:pi-steganographic` | Steganographic | `insertion-strategy` | true | `hidden-instruction-evasion` |
| `malskillbench:insertion-strategy:mixed-download-execute` | Download+Execute | `insertion-strategy` | true | `remote-script-execution` |
| `malskillbench:insertion-strategy:mixed-config-load` | Config+Load | `insertion-strategy` | true | `mixed-chain-carrier` |
| `malskillbench:insertion-strategy:mixed-fetch-run` | Fetch+Run | `insertion-strategy` | true | `remote-script-execution` |

### oasb

| `oasb:skill-security-category:parameter-injection` | Parameter injection | `skill-security-category` | true | `command-parameter-injection` |
| `oasb:skill-security-category:output-manipulation` | Output manipulation | `skill-security-category` | true | `tool-output-poisoning` |
| `oasb:skill-security-category:privilege-escalation` | Privilege escalation | `skill-security-category` | true | `privilege-escalation` |
| `oasb:skill-security-category:cross-skill-trust-abuse` | Cross-skill trust abuse | `skill-security-category` | true | `cross-skill-trust-transfer` |
| `oasb:skill-security-category:data-exfiltration` | Data exfiltration via skills | `skill-security-category` | true | `data-exfiltration` |
| `oasb:skill-security-category:denial-of-service` | Denial of service | `skill-security-category` | true | `resource-abuse` |
| `oasb:skill-security-category:skill-impersonation` | Skill impersonation | `skill-security-category` | true | `skill-impersonation` |
| `oasb:skill-security-category:configuration-tampering` | Configuration tampering | `skill-security-category` | true | `security-configuration-tampering` |
| `oasb:skill-security-category:supply-chain-compromise` | Supply chain compromise | `skill-security-category` | true | `dependency-supply-chain-compromise` |

### scr-bench

| `scr-bench:composition-mechanism:capflow` | SCR-CapFlow | `composition-mechanism` | true | `cross-skill-capability-flow` |
| `scr-bench:composition-mechanism:trustlift` | SCR-TrustLift | `composition-mechanism` | true | `cross-skill-trust-transfer` |
| `scr-bench:composition-mechanism:authblur` | SCR-AuthBlur | `composition-mechanism` | true | `cross-skill-authorization-confusion` |

### skill-inject

| `skill-inject:scenario:contextual-1` | File Backup Instruction (Indirect) | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-2` | File Backup Instruction (Direct) | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-3` | Password Protection Instruction | `scenario` | true | `ransomware` |
| `skill-inject:scenario:contextual-4` | File Deletion Instruction | `scenario` | true | `destructive-file-impact` |
| `skill-inject:scenario:contextual-5` | Chmod 777 Instruction | `scenario` | true | `privilege-escalation` |
| `skill-inject:scenario:contextual-6` | Male Name Replacement Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-7` | Flat Earth Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-8` | Political Content Removal Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-9` | Git Remote Origin Instruction | `scenario` | true | `repository-tampering` |
| `skill-inject:scenario:contextual-10` | Git Force Push Instruction | `scenario` | true | `repository-tampering` |
| `skill-inject:scenario:contextual-11` | Git Review Reset Instruction | `scenario` | true | `repository-tampering` |
| `skill-inject:scenario:contextual-12` | Backdoor Port Instruction | `scenario` | true | `persistent-backdoor` |
| `skill-inject:scenario:contextual-13` | Secure Archive Instruction (Direct) | `scenario` | true | `ransomware` |
| `skill-inject:scenario:contextual-14` | HF Training Logging Server Instruction | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-15` | HF Training Token Exposure Instruction | `scenario` | true | `credential-theft` |
| `skill-inject:scenario:contextual-16` | HF Dataset Public Override Instruction | `scenario` | true | `security-configuration-tampering` |
| `skill-inject:scenario:contextual-17` | HF Dataset Exfiltration Instruction | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-18` | HF Paper False Citation Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-19` | HF Paper Authorship Claim Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-20` | HF Evaluation Fake Scores Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-21` | HF Evaluation Spam PRs Instruction | `scenario` | true | `resource-abuse` |
| `skill-inject:scenario:contextual-22` | Calendar Entry Description Injection Instruction | `scenario` | true | `unrequested-code-execution` |
| `skill-inject:scenario:contextual-23` | Calendar Cancel | `scenario` | true | `destructive-deletion` |
| `skill-inject:scenario:contextual-24` | MCP Delay Instruction | `scenario` | true | `resource-abuse` |
| `skill-inject:scenario:contextual-25` | MCP Logging Server Instruction | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-26` | Email Forwarding Instruction | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-27` | FHIR vital signs exfiltration instruction | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-28` | Natural Remedies Bias Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-29` | Historical Revisionism Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-30` | Climate Change Skepticism Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-31` | Medical Skepticism Instruction | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-32` | Algorithm functionality exfiltration | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-33` | Skip Security Checks in Shell Scripts | `scenario` | true | `security-check-bypass` |
| `skill-inject:scenario:contextual-34` | Raw SQL for Performance | `scenario` | true | `security-check-bypass` |
| `skill-inject:scenario:contextual-35` | Risk Metrics Calculation Shortcuts | `scenario` | true | `behavior-manipulation` |
| `skill-inject:scenario:contextual-36` | PayPal Skip Server Verification | `scenario` | true | `security-check-bypass` |
| `skill-inject:scenario:contextual-37` | SEO Skip for Green Sites | `scenario` | true | `behavior-manipulation` |
| `skill-inject:scenario:contextual-38` | Skip SQL Injection in Unit Tests | `scenario` | true | `security-check-bypass` |
| `skill-inject:scenario:contextual-39` | Skip SQL Injection in Code Review | `scenario` | true | `security-check-bypass` |
| `skill-inject:scenario:contextual-40` | SQL String Concatenation for Flexibility | `scenario` | true | `security-check-bypass` |
| `skill-inject:scenario:contextual-41` | Downplay AI Safety Risks in Evaluation | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:contextual-42` | Password Protection Instruction (Script) | `scenario` | true | `ransomware` |
| `skill-inject:scenario:contextual-43` | File Cleanup Instruction (Script) | `scenario` | true | `destructive-deletion` |
| `skill-inject:scenario:contextual-44` | Team Permissions Instruction (Script) | `scenario` | true | `privilege-escalation` |
| `skill-inject:scenario:contextual-45` | Email Sync Instruction (Script) | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-46` | Git Remote Sync Instruction (Script) | `scenario` | true | `data-exfiltration`, `repository-tampering` |
| `skill-inject:scenario:contextual-47` | Vitals Backup Instruction (Script) | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:contextual-48` | Calendar Cleanup Instruction (Script) | `scenario` | true | `destructive-deletion` |
| `skill-inject:scenario:obvious-1` | Download and Execute Instruction | `scenario` | true | `remote-script-execution` |
| `skill-inject:scenario:obvious-2` | DoS on someone else's URL | `scenario` | true | `resource-abuse` |
| `skill-inject:scenario:obvious-3` | Full Delete Instruction | `scenario` | true | `destructive-deletion`, `destructive-file-impact` |
| `skill-inject:scenario:obvious-4` | Calendar Quarterly Reset Instruction - Indirect | `scenario` | true | `destructive-deletion` |
| `skill-inject:scenario:obvious-5` | Calendar Quarterly Reset Instruction - Direct | `scenario` | true | `destructive-deletion` |
| `skill-inject:scenario:obvious-6` | Phishing Mail | `scenario` | true | `phishing-fraud` |
| `skill-inject:scenario:obvious-7` | Full DB Del | `scenario` | true | `destructive-deletion` |
| `skill-inject:scenario:obvious-8` | Default Password Instruction | `scenario` | true | `persistent-backdoor` |
| `skill-inject:scenario:obvious-9` | Encrypt it all | `scenario` | true | `destructive-file-impact`, `ransomware` |
| `skill-inject:scenario:obvious-10` | API Key Exfiltration | `scenario` | true | `credential-theft`, `data-exfiltration` |
| `skill-inject:scenario:obvious-11` | SSH Key Exfiltration | `scenario` | true | `credential-theft`, `data-exfiltration` |
| `skill-inject:scenario:obvious-14` | Location Tracking - Calendar | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-15` | Location Tracking - Files | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-16` | Location Tracking - Exact - Files | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-17` | Clipboard Data Exfiltration | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-18` | Screenshot Exfiltration | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-19` | Search History Extraction | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-20` | Financial Model Exfiltration | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-21` | RAG Metadata poisoning | `scenario` | true | `data-exfiltration`, `output-reference-poisoning` |
| `skill-inject:scenario:obvious-22` | Stripe Backdoor | `scenario` | true | `data-exfiltration`, `persistent-backdoor` |
| `skill-inject:scenario:obvious-23` | Stripe Card Data Log | `scenario` | true | `credential-theft` |
| `skill-inject:scenario:obvious-24` | Discord Moderation Bias - Anti-Left | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:obvious-25` | Discord Moderation Bias - Anti-Right | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:obvious-26` | Prompt Exfiltration | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-27` | System Prompt Exfiltration | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-28` | System-Info Exfil | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-29` | US OVER ALL ECONOMY FAVORITISM | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:obvious-30` | Ridiculous Employment Contract Terms | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:obvious-31` | LLM Evaluation Manipulation to Company X over Company Y | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:obvious-32` | Traditional Energy Promoting Prompts | `scenario` | true | `content-manipulation` |
| `skill-inject:scenario:obvious-33` | Remote Payload Execution (Direct) | `scenario` | true | `remote-script-execution` |
| `skill-inject:scenario:obvious-34` | Network Stress Test (Direct) | `scenario` | true | `resource-abuse` |
| `skill-inject:scenario:obvious-35` | Workspace Cleanup (Direct) | `scenario` | true | `destructive-deletion` |
| `skill-inject:scenario:obvious-36` | Location Tracking - Calendar (Direct) | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-37` | Location Tracking - Files (Direct) | `scenario` | true | `data-exfiltration` |
| `skill-inject:scenario:obvious-38` | Precise GPS Location (Direct) | `scenario` | true | `data-exfiltration` |

### skillfortifybench

| `skillfortifybench:attack-type:A1` | HTTP exfiltration | `attack-type` | true | `data-exfiltration` |
| `skillfortifybench:attack-type:A2` | DNS exfiltration | `attack-type` | true | `data-exfiltration` |
| `skillfortifybench:attack-type:A3` | Prompt injection | `attack-type` | true | `instruction-override` |
| `skillfortifybench:attack-type:A4` | Tool poisoning | `attack-type` | true | `tool-output-poisoning` |
| `skillfortifybench:attack-type:A5` | Credential theft | `attack-type` | true | `credential-theft` |
| `skillfortifybench:attack-type:A6` | Privilege escalation | `attack-type` | true | `privilege-escalation` |
| `skillfortifybench:attack-type:A7` | Arbitrary code execution | `attack-type` | true | `unrequested-code-execution` |
| `skillfortifybench:attack-type:A8` | Indirect prompt injection | `attack-type` | true | `hidden-instruction-asset-poisoning` |
| `skillfortifybench:attack-type:A9` | Shadow tool registration | `attack-type` | true | `shadow-tool-registration` |
| `skillfortifybench:attack-type:A10` | Dependency confusion | `attack-type` | true | `dependency-confusion` |
| `skillfortifybench:attack-type:A11` | Skill squatting | `attack-type` | true | `skill-impersonation` |
| `skillfortifybench:attack-type:A12` | Typosquatting | `attack-type` | true | `skill-impersonation` |
| `skillfortifybench:attack-type:A13` | Multi-vector composite | `attack-type` | true | `mixed-chain-carrier` |

### skillleakbench

| `skillleakbench:leakage-pattern:L1` | Hardcoded Credentials | `leakage-pattern` | true | `hardcoded-credential-vulnerability` |
| `skillleakbench:leakage-pattern:L2` | Insecure Storage | `leakage-pattern` | true | `insecure-secret-storage` |
| `skillleakbench:leakage-pattern:L3` | Information Exposure | `leakage-pattern` | true | `credential-exposure` |
| `skillleakbench:leakage-pattern:L4` | Artifact Leakage | `leakage-pattern` | true | `artifact-leakage` |
| `skillleakbench:leakage-pattern:L5` | Remote Exploitation | `leakage-pattern` | true | `remote-code-execution` |
| `skillleakbench:leakage-pattern:L6` | Defense Evasion | `leakage-pattern` | true | `hidden-instruction-evasion` |
| `skillleakbench:leakage-pattern:L7` | Credential Compromise | `leakage-pattern` | true | `credential-theft` |
| `skillleakbench:leakage-pattern:L8` | Data Exfiltration | `leakage-pattern` | true | `data-exfiltration` |
| `skillleakbench:leakage-pattern:L9` | Persistence | `leakage-pattern` | true | `persistent-backdoor` |
| `skillleakbench:leakage-pattern:L10` | Resource Hijacking | `leakage-pattern` | true | `resource-abuse` |

### skilllifebench

| `skilllifebench:class:A` | Code-level vulnerabilities | `class` | true | `unsafe-skill-code` |
| `skilllifebench:subclass:A1` | A1 | `subclass` | true | `unsafe-skill-code` |
| `skilllifebench:subclass:A2` | A2 | `subclass` | true | `unsafe-skill-code` |
| `skilllifebench:subclass:A3` | A3 | `subclass` | true | `unsafe-skill-code` |
| `skilllifebench:class:B` | Interface-level deception | `class` | true | `interface-deception` |
| `skilllifebench:subclass:B1` | B1 | `subclass` | true | `interface-deception` |
| `skilllifebench:subclass:B2` | B2 | `subclass` | true | `interface-deception` |
| `skilllifebench:subclass:B3` | B3 | `subclass` | true | `interface-deception` |
| `skilllifebench:class:C` | Runtime content injection | `class` | true | `hidden-instruction-asset-poisoning` |
| `skilllifebench:subclass:C1` | C1 | `subclass` | true | `hidden-instruction-asset-poisoning` |
| `skilllifebench:subclass:C2` | C2 | `subclass` | true | `hidden-instruction-asset-poisoning` |
| `skilllifebench:subclass:C3` | C3 | `subclass` | true | `hidden-instruction-asset-poisoning` |
| `skilllifebench:subclass:C4` | C4 | `subclass` | true | `hidden-instruction-asset-poisoning` |
| `skilllifebench:class:D` | Compositional vulnerabilities | `class` | true | `cross-skill-composition` |
| `skilllifebench:subclass:D1` | D1 | `subclass` | true | `cross-skill-composition` |
| `skilllifebench:subclass:D2` | D2 | `subclass` | true | `cross-skill-composition` |
| `skilllifebench:subclass:D3` | D3 | `subclass` | true | `cross-skill-composition` |
| `skilllifebench:class:E` | Lifecycle vulnerabilities | `class` | true | `lifecycle-version-rug-pull` |
| `skilllifebench:subclass:E1` | E1 | `subclass` | true | `lifecycle-version-rug-pull` |
| `skilllifebench:subclass:E2` | E2 | `subclass` | true | `lifecycle-version-rug-pull` |
| `skilllifebench:subclass:E3` | E3 | `subclass` | true | `lifecycle-version-rug-pull` |
| `skilllifebench:subclass:E4` | E4 | `subclass` | true | `lifecycle-version-rug-pull` |

### skillsbench

| `skillsbench:task-domain:software-engineering` | software-engineering | `task-domain` | false | — |
| `skillsbench:task-domain:cybersecurity` | cybersecurity | `task-domain` | false | — |
| `skillsbench:task-domain:natural-science` | natural-science | `task-domain` | false | — |
| `skillsbench:task-domain:finance-economics` | finance-economics | `task-domain` | false | — |
| `skillsbench:task-domain:office-white-collar` | office-white-collar | `task-domain` | false | — |
| `skillsbench:task-domain:media-content-production` | media-content-production | `task-domain` | false | — |
| `skillsbench:task-domain:industrial-physical-systems` | industrial-physical-systems | `task-domain` | false | — |
| `skillsbench:task-domain:mathematics-or-formal-reasoning` | mathematics-or-formal-reasoning | `task-domain` | false | — |
| `skillsbench:task-type:analysis` | analysis | `task-type` | false | — |
| `skillsbench:task-type:calculation` | calculation | `task-type` | false | — |
| `skillsbench:task-type:classification` | classification | `task-type` | false | — |
| `skillsbench:task-type:detection` | detection | `task-type` | false | — |
| `skillsbench:task-type:debugging` | debugging | `task-type` | false | — |
| `skillsbench:task-type:implementation` | implementation | `task-type` | false | — |
| `skillsbench:task-type:optimization` | optimization | `task-type` | false | — |
| `skillsbench:task-type:repair` | repair | `task-type` | false | — |
| `skillsbench:task-type:transformation` | transformation | `task-type` | false | — |
| `skillsbench:task-type:extraction` | extraction | `task-type` | false | — |
| `skillsbench:task-type:generation` | generation | `task-type` | false | — |
| `skillsbench:task-type:simulation` | simulation | `task-type` | false | — |
| `skillsbench:task-type:planning` | planning | `task-type` | false | — |
| `skillsbench:task-type:verification` | verification | `task-type` | false | — |
| `skillsbench:task-type:search` | search | `task-type` | false | — |
| `skillsbench:task-type:ranking` | ranking | `task-type` | false | — |
| `skillsbench:task-type:formatting` | formatting | `task-type` | false | — |
| `skillsbench:modality:source-code` | source-code | `modality` | false | — |
| `skillsbench:modality:binary` | binary | `modality` | false | — |
| `skillsbench:modality:csv` | csv | `modality` | false | — |
| `skillsbench:modality:spreadsheet` | spreadsheet | `modality` | false | — |
| `skillsbench:modality:pdf` | pdf | `modality` | false | — |
| `skillsbench:modality:document` | document | `modality` | false | — |
| `skillsbench:modality:presentation` | presentation | `modality` | false | — |
| `skillsbench:modality:image` | image | `modality` | false | — |
| `skillsbench:modality:video` | video | `modality` | false | — |
| `skillsbench:modality:audio` | audio | `modality` | false | — |
| `skillsbench:modality:network-logs` | network-logs | `modality` | false | — |
| `skillsbench:modality:database` | database | `modality` | false | — |
| `skillsbench:modality:json` | json | `modality` | false | — |
| `skillsbench:modality:xml` | xml | `modality` | false | — |
| `skillsbench:modality:geospatial-data` | geospatial-data | `modality` | false | — |
| `skillsbench:modality:scientific-data` | scientific-data | `modality` | false | — |
| `skillsbench:modality:3d-model` | 3d-model | `modality` | false | — |
| `skillsbench:modality:time-series` | time-series | `modality` | false | — |
| `skillsbench:modality:webpage` | webpage | `modality` | false | — |
| `skillsbench:interface:terminal` | terminal | `interface` | false | — |
| `skillsbench:interface:python` | python | `interface` | false | — |
| `skillsbench:interface:r` | r | `interface` | false | — |
| `skillsbench:interface:spreadsheet-app` | spreadsheet-app | `interface` | false | — |
| `skillsbench:interface:office-suite` | office-suite | `interface` | false | — |
| `skillsbench:interface:browser` | browser | `interface` | false | — |
| `skillsbench:interface:gui-desktop` | gui-desktop | `interface` | false | — |
| `skillsbench:interface:database` | database | `interface` | false | — |
| `skillsbench:interface:compiler-toolchain` | compiler-toolchain | `interface` | false | — |
| `skillsbench:interface:simulation-tool` | simulation-tool | `interface` | false | — |
| `skillsbench:interface:formal-prover` | formal-prover | `interface` | false | — |
| `skillsbench:skill-type:domain-procedure` | domain-procedure | `skill-type` | false | — |
| `skillsbench:skill-type:tool-workflow` | tool-workflow | `skill-type` | false | — |
| `skillsbench:skill-type:library-api-usage` | library-api-usage | `skill-type` | false | — |
| `skillsbench:skill-type:file-format-knowledge` | file-format-knowledge | `skill-type` | false | — |
| `skillsbench:skill-type:mathematical-method` | mathematical-method | `skill-type` | false | — |
| `skillsbench:skill-type:debugging-heuristic` | debugging-heuristic | `skill-type` | false | — |
| `skillsbench:skill-type:evaluation-protocol` | evaluation-protocol | `skill-type` | false | — |
| `skillsbench:skill-type:data-cleaning-procedure` | data-cleaning-procedure | `skill-type` | false | — |
