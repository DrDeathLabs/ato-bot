const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  TableOfContents
} = require('docx');
const fs = require('fs');

// ── Colors ────────────────────────────────────────────────────────────────────
const NAVY   = "1F3864";
const BLUE   = "2E5FAC";
const LTBLUE = "D6E4F7";
const GRAY   = "F2F2F2";
const RED    = "C00000";
const ORANGE = "C55A11";

// ── Border helpers ─────────────────────────────────────────────────────────────
const border = (color = "CCCCCC", size = 4) => ({ style: BorderStyle.SINGLE, size, color });
const allBorders = (color = "CCCCCC") => ({ top: border(color), bottom: border(color), left: border(color), right: border(color) });
const noBorder = () => ({ style: BorderStyle.NONE, size: 0, color: "FFFFFF" });
const noBorders = () => ({ top: noBorder(), bottom: noBorder(), left: noBorder(), right: noBorder() });

// ── Text helpers ───────────────────────────────────────────────────────────────
const t = (text, opts = {}) => new TextRun({ text, font: "Arial", ...opts });
const bold = (text, opts = {}) => t(text, { bold: true, ...opts });
const p = (children, opts = {}) => new Paragraph({ children: Array.isArray(children) ? children : [children], spacing: { after: 120 }, ...opts });
const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  children: [new TextRun({ text, font: "Arial", size: 32, bold: true, color: NAVY })],
  spacing: { before: 400, after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BLUE, space: 4 } }
});
const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  children: [new TextRun({ text, font: "Arial", size: 26, bold: true, color: BLUE })],
  spacing: { before: 280, after: 120 }
});
const h3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  children: [new TextRun({ text, font: "Arial", size: 24, bold: true, color: "404040" })],
  spacing: { before: 200, after: 80 }
});
const bullet = (text, opts = {}) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  children: [new TextRun({ text, font: "Arial", size: 20, ...opts })],
  spacing: { after: 60 }
});
const body = (text) => p([t(text, { size: 20 })]);
const spacer = () => new Paragraph({ children: [t("")], spacing: { after: 80 } });

// ── Cell helpers ───────────────────────────────────────────────────────────────
const cell = (text, width, opts = {}) => new TableCell({
  width: { size: width, type: WidthType.DXA },
  borders: allBorders("CCCCCC"),
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 18, ...opts })] })],
  ...opts.cellOpts
});
const headerCell = (text, width, fill = BLUE) => new TableCell({
  width: { size: width, type: WidthType.DXA },
  borders: allBorders(NAVY),
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  shading: { fill, type: ShadingType.CLEAR },
  children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 18, bold: true, color: fill === LTBLUE ? NAVY : "FFFFFF" })] })]
});
const shadeCell = (text, width) => new TableCell({
  width: { size: width, type: WidthType.DXA },
  borders: allBorders("CCCCCC"),
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  shading: { fill: GRAY, type: ShadingType.CLEAR },
  children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 18, bold: true })] })]
});
const labelCell = (text, width) => new TableCell({
  width: { size: width, type: WidthType.DXA },
  borders: allBorders("CCCCCC"),
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  shading: { fill: LTBLUE, type: ShadingType.CLEAR },
  children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 18, bold: true, color: NAVY })] })]
});

// ── Page break ─────────────────────────────────────────────────────────────────
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

// ── Control implementation paragraph ──────────────────────────────────────────
const controlBlock = (id, title, impl) => [
  new Paragraph({
    children: [
      new TextRun({ text: `${id} `, font: "Arial", size: 20, bold: true, color: BLUE }),
      new TextRun({ text: title, font: "Arial", size: 20, bold: true })
    ],
    spacing: { before: 160, after: 60 },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: BLUE, space: 6 } },
    indent: { left: 180 }
  }),
  new Paragraph({
    children: [new TextRun({ text: impl, font: "Arial", size: 20 })],
    spacing: { after: 120 },
    indent: { left: 180 }
  })
];

// ── POA&M row ─────────────────────────────────────────────────────────────────
const poamRow = (id, control, finding, risk, plan, responsible, eta, riskColor) => new TableRow({
  children: [
    new TableCell({
      width: { size: 700, type: WidthType.DXA },
      borders: allBorders("CCCCCC"),
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: id, font: "Arial", size: 18, bold: true })] })]
    }),
    new TableCell({
      width: { size: 1000, type: WidthType.DXA },
      borders: allBorders("CCCCCC"),
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: control, font: "Arial", size: 18, bold: true })] })]
    }),
    new TableCell({
      width: { size: 2560, type: WidthType.DXA },
      borders: allBorders("CCCCCC"),
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: finding, font: "Arial", size: 17 })] })]
    }),
    new TableCell({
      width: { size: 600, type: WidthType.DXA },
      borders: allBorders("CCCCCC"),
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      shading: { fill: riskColor, type: ShadingType.CLEAR },
      children: [new Paragraph({ children: [new TextRun({ text: risk, font: "Arial", size: 18, bold: true, color: "FFFFFF" })] })]
    }),
    new TableCell({
      width: { size: 2400, type: WidthType.DXA },
      borders: allBorders("CCCCCC"),
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: plan, font: "Arial", size: 17 })] })]
    }),
    new TableCell({
      width: { size: 1200, type: WidthType.DXA },
      borders: allBorders("CCCCCC"),
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [
        new Paragraph({ children: [new TextRun({ text: responsible, font: "Arial", size: 17 })] }),
        new Paragraph({ children: [new TextRun({ text: eta, font: "Arial", size: 17, italics: true, color: "666666" })] })
      ]
    }),
  ]
});

// ── Document ──────────────────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 560, hanging: 280 } } }
        }]
      }
    ]
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 400, after: 200 }, outlineLevel: 0 }
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 }
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "404040" },
        paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 }
      },
    ]
  },
  sections: [
    // ── COVER PAGE ─────────────────────────────────────────────────────────────
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      children: [
        spacer(), spacer(), spacer(),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "CUI // FOR OFFICIAL USE ONLY", font: "Arial", size: 20, bold: true, color: RED })],
          spacing: { after: 80 }
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "CONTROLLED UNCLASSIFIED INFORMATION", font: "Arial", size: 18, color: RED })],
          spacing: { after: 800 }
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "GovConnect Portal", font: "Arial", size: 64, bold: true, color: NAVY })],
          spacing: { after: 160 }
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Authority to Operate (ATO) Package", font: "Arial", size: 36, color: BLUE })],
          spacing: { after: 160 }
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "System Security Plan, Information Security Policy, and Plan of Action & Milestones", font: "Arial", size: 22, color: "555555", italics: true })],
          spacing: { after: 800 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: BLUE, space: 12 } }
        }),
        spacer(),
        new Table({
          width: { size: 6000, type: WidthType.DXA },
          columnWidths: [2000, 4000],
          rows: [
            new TableRow({ children: [labelCell("System Name", 2000), cell("GovConnect Portal", 4000)] }),
            new TableRow({ children: [labelCell("Document Type", 2000), cell("ATO Package — SSP / Policy / POA&M", 4000)] }),
            new TableRow({ children: [labelCell("Version", 2000), cell("1.0", 4000)] }),
            new TableRow({ children: [labelCell("Date", 2000), cell("March 2026", 4000)] }),
            new TableRow({ children: [labelCell("Classification", 2000), cell("CUI // FOR OFFICIAL USE ONLY", 4000, { color: RED, bold: true })] }),
            new TableRow({ children: [labelCell("Impact Level", 2000), cell("MODERATE (NIST SP 800-53 Rev 5)", 4000)] }),
            new TableRow({ children: [labelCell("Operating Env.", 2000), cell("AWS GovCloud (us-gov-west-1)", 4000)] }),
          ]
        }),
        spacer(), spacer(), spacer(), spacer(),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Department of Citizen Services", font: "Arial", size: 22, bold: true, color: NAVY })],
          spacing: { after: 80 }
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "Information Security Division", font: "Arial", size: 20, color: "555555" })],
          spacing: { after: 200 }
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "DISTRIBUTION LIMITED TO AUTHORIZED PERSONNEL ONLY", font: "Arial", size: 18, bold: true, color: RED })],
          spacing: { after: 80 }
        }),
        pageBreak()
      ],
      headers: { default: new Header({ children: [new Paragraph({ children: [] })] }) },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "CUI // FOR OFFICIAL USE ONLY — GovConnect Portal ATO Package v1.0 — March 2026", font: "Arial", size: 16, color: RED })]
          })]
        })
      }
    },

    // ── MAIN CONTENT ───────────────────────────────────────────────────────────
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            children: [
              new TextRun({ text: "GovConnect Portal — ATO Package", font: "Arial", size: 18, bold: true, color: NAVY }),
              new TextRun({ text: "\t\tCUI // FOUO", font: "Arial", size: 18, color: RED, bold: true })
            ],
            tabStops: [{ type: "right", position: 9360 }],
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 4 } }
          })]
        })
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            children: [
              new TextRun({ text: "DCS-ATO-001 v1.0  |  March 2026  |  Page ", font: "Arial", size: 16, color: "666666" }),
              new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: "666666" }),
              new TextRun({ text: " of ", font: "Arial", size: 16, color: "666666" }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 16, color: "666666" })
            ],
            alignment: AlignmentType.CENTER,
            border: { top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 4 } }
          })]
        })
      },
      children: [
        // TOC
        new Paragraph({
          heading: HeadingLevel.HEADING_1,
          children: [new TextRun({ text: "Table of Contents", font: "Arial", size: 32, bold: true, color: NAVY })],
          spacing: { before: 0, after: 200 }
        }),
        new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" }),
        pageBreak(),

        // ═════════════════════════════════════════════════════════════════════
        // SECTION 1 — SYSTEM SECURITY PLAN
        // ═════════════════════════════════════════════════════════════════════
        h1("1. System Security Plan (SSP)"),
        body("This System Security Plan describes the security controls implemented for GovConnect Portal in accordance with NIST SP 800-53 Rev 5 at the MODERATE impact baseline, FISMA, and OMB Circular A-130."),

        h2("1.1 System Identification"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [3000, 6360],
          rows: [
            new TableRow({ children: [labelCell("System Name", 3000), cell("GovConnect Portal", 6360)] }),
            new TableRow({ children: [labelCell("System Abbreviation", 3000), cell("GCP", 6360)] }),
            new TableRow({ children: [labelCell("Unique Identifier", 3000), cell("DCS-MAJOR-0042", 6360)] }),
            new TableRow({ children: [labelCell("System Type", 3000), cell("Major Application", 6360)] }),
            new TableRow({ children: [labelCell("Operating Status", 3000), cell("Operational", 6360)] }),
            new TableRow({ children: [labelCell("Impact Level", 3000), cell("MODERATE", 6360)] }),
            new TableRow({ children: [labelCell("Operating Environment", 3000), cell("AWS GovCloud (us-gov-west-1)", 6360)] }),
            new TableRow({ children: [labelCell("Data Sensitivity", 3000), cell("CUI, Personally Identifiable Information (PII)", 6360)] }),
            new TableRow({ children: [labelCell("System Owner", 3000), cell("Jane Mitchell, jane.mitchell@dcs.gov", 6360)] }),
            new TableRow({ children: [labelCell("ISSO", 3000), cell("Marcus Webb, marcus.webb@dcs.gov", 6360)] }),
            new TableRow({ children: [labelCell("Authorizing Official", 3000), cell("Deputy Director Thomas Harrington", 6360)] }),
            new TableRow({ children: [labelCell("SSP Version", 3000), cell("1.0", 6360)] }),
            new TableRow({ children: [labelCell("SSP Date", 3000), cell("March 2026", 6360)] }),
          ]
        }),

        spacer(),
        h2("1.2 System Description"),
        body("GovConnect Portal is a web-based citizen services platform operated by the Department of Citizen Services (DCS). The system enables citizens to authenticate via Login.gov (federated SSO at IAL2/AAL2), submit benefit applications, upload supporting documentation (pay stubs, birth certificates, tax records), and track application status in real time. Internal DCS staff access a separate administrative interface to review submissions, make eligibility determinations, and communicate decisions."),
        body("The system processes Controlled Unclassified Information (CUI) and Personally Identifiable Information (PII) including Social Security Numbers, financial records, and family composition data. The Confidentiality, Integrity, and Availability impact ratings are all MODERATE, establishing the system at the NIST MODERATE baseline requiring implementation of approximately 330 controls."),

        h2("1.3 System Architecture and Boundary"),
        body("The system boundary encompasses the following components hosted in AWS GovCloud (us-gov-west-1):"),
        bullet("Web Application Tier: Python/Django application deployed on EC2 instances in an Auto Scaling Group (ASG), fronted by an AWS Application Load Balancer (ALB) with WAF. EC2 instances use Amazon Linux 2023."),
        bullet("Database Tier: PostgreSQL 15 on Amazon RDS Multi-AZ (primary in us-gov-west-1a, standby in us-gov-west-1b). pgaudit extension enabled for database audit logging."),
        bullet("Session Cache: Redis 7.0 on Amazon ElastiCache (cluster mode disabled, single-shard, encrypted at rest and in transit)."),
        bullet("Document Storage: Amazon S3 buckets with SSE-KMS encryption, versioning enabled, and block public access settings enforced."),
        bullet("PDF Processing: AWS Lambda function (Python 3.12 runtime) invoked asynchronously for document normalization and text extraction. Lambda VPC-enabled, placed in private subnet."),
        bullet("Identity Provider: Login.gov (external FICAM-approved CSP) for citizen authentication. AWS IAM Identity Center + Okta for staff authentication."),
        bullet("Logging and Monitoring: Amazon CloudWatch (logs and metrics), AWS Security Hub, AWS GuardDuty, AWS Inspector, AWS CloudTrail (API-level audit). AWS Config for compliance monitoring."),

        spacer(),
        h2("1.4 Account Summary"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2200, 2400, 2400, 2360],
          rows: [
            new TableRow({ children: [headerCell("Account Type", 2200), headerCell("Count", 2400), headerCell("Provisioning Method", 2400), headerCell("Review Frequency", 2360)] }),
            new TableRow({ children: [cell("Citizen (Public)", 2200), cell("Self-registered (Login.gov)", 2400), cell("Login.gov federated SSO", 2400), cell("Event-driven (inactivity 365 days)", 2360)] }),
            new TableRow({ children: [cell("Staff (Case Worker)", 2200), cell("32", 2400), cell("ServiceNow + Manager/ISSO approval", 2400), cell("Quarterly", 2360)] }),
            new TableRow({ children: [cell("Staff (Supervisor)", 2200), cell("7", 2400), cell("ServiceNow + Director approval", 2400), cell("Quarterly", 2360)] }),
            new TableRow({ children: [cell("Admin (Privileged)", 2200), cell("8", 2400), cell("ServiceNow + ISSO + Director approval", 2400), cell("Quarterly", 2360)] }),
            new TableRow({ children: [cell("Service Accounts", 2200), cell("6", 2400), cell("IAM Roles (no long-term keys)", 2400), cell("Annual (credential review)", 2360)] }),
          ]
        }),

        spacer(),
        h2("1.5 Control Implementation Statements"),
        body("The following sections describe the implementation of selected NIST SP 800-53 Rev 5 security controls for GovConnect Portal."),

        h3("1.5.1 Access Control (AC) Family"),
        ...controlBlock("AC-1", "Access Control Policy and Procedures",
          "GovConnect Portal maintains an Access Control Policy (Document DCS-AC-001, Version 2.1, last reviewed January 2026). The policy covers all aspects of system access including account provisioning, least privilege, separation of duties, and remote access. The policy is reviewed and updated annually by the ISSO in coordination with the System Owner. Supporting access control procedures are documented in DCS-AC-001-P and reviewed semi-annually."),
        ...controlBlock("AC-2", "Account Management",
          "User accounts are provisioned via ServiceNow ticketing workflow. New staff accounts require: (1) manager approval request, (2) ISSO review and sign-off, (3) automated provisioning via AWS IAM Identity Center. Accounts are reviewed quarterly — the ISSO generates an access report from AWS IAM and compares against active HR records. Terminated employee accounts are automatically disabled within 4 hours via integration with the DCS HR system (Workday). Accounts inactive for 45 days generate an alert; accounts inactive 90 days are disabled pending review. Privileged accounts require written justification and Deputy Director approval. Account types: citizen (self-registered via Login.gov, not managed by DCS), staff/supervisor (provisioned), admin (individually justified), service (IAM roles, no interactive login)."),
        ...controlBlock("AC-3", "Access Enforcement",
          "Role-based access control (RBAC) is enforced server-side at the Django application layer. Three roles are defined: citizen, case_worker, and supervisor. Citizens can only access and view their own records — all data queries include user_id filter enforced at the ORM layer. Case workers can view records assigned to their queue. Supervisors can view all records within their geographic region. Access control decisions are made server-side exclusively; no security-relevant decisions rely on client-side code. AWS Security Groups enforce network-layer access restrictions: the ALB accepts internet traffic on 443/TCP only, application instances accept traffic only from the ALB security group, and database/cache instances accept traffic only from the application tier security group."),
        ...controlBlock("AC-7", "Unsuccessful Logon Attempts",
          "For citizen-facing authentication: Login.gov enforces account lockout after 5 consecutive failed authentication attempts with a 15-minute lockout period. GovConnect does not manage citizen credentials. For the staff administrative interface: 3 consecutive failed authentication attempts trigger immediate account lockout. Lockout requires manual ISSO intervention to unlock. All failed logon attempts are logged to CloudWatch with timestamp, username, source IP, and user agent. AWS Security Hub generates an alert when more than 5 failed attempts occur within a 10-minute window from a single IP address."),
        ...controlBlock("AC-17", "Remote Access",
          "All remote administrative access to GovConnect infrastructure requires connection through AWS Client VPN using certificate-based mutual TLS authentication. Multi-factor authentication (hardware TOTP token) is required for all privileged remote sessions. VPN sessions are limited to 8 hours; re-authentication required at session expiration. All remote access sessions generate CloudTrail events and CloudWatch logs, reviewed weekly by the ISSO. Third-party vendor remote access is strictly prohibited without prior written approval from the System Owner and ISSO. Approved vendor access is time-limited and monitored in real time."),

        h3("1.5.2 Audit and Accountability (AU) Family"),
        ...controlBlock("AU-2", "Event Logging",
          "The following events are logged by GovConnect Portal: (1) user logon and logoff events — successful and failed — including source IP, timestamp, and session ID; (2) account creation, modification, suspension, and deletion; (3) privilege escalation and role assignment changes; (4) document upload and download events including file name, user, and timestamp; (5) access to sensitive data fields (SSN, financial data) logged at the application layer; (6) system configuration changes via AWS Config and CloudTrail; (7) application errors (HTTP 500-level) with stack traces sanitized to remove PII; (8) network-layer events via VPC Flow Logs (accepted and rejected connections). The audit event list is reviewed annually by the ISSO in coordination with the System Owner."),
        ...controlBlock("AU-3", "Content of Audit Records",
          "Each audit record contains the following mandatory fields: timestamp (UTC, synchronized via AWS Time Sync Service — NTP), event type/category, user identifier (staff username or citizen session token hash — never cleartext PII), source IP address, session identifier, resource affected (table name, S3 bucket, API endpoint), action taken (CRUD operation or specific action), and outcome (success or failure with error code). RDS audit records include database username, client address, command type, and affected objects (pgaudit extension). CloudTrail records include IAM principal, API action, request parameters (sanitized), and response elements."),
        ...controlBlock("AU-6", "Audit Record Review, Analysis, and Reporting",
          "Audit logs are reviewed weekly by the ISSO using AWS Security Hub consolidated dashboard and custom CloudWatch Insights queries. Automated CloudWatch alarms trigger alerts for: more than 5 failed login attempts from a single IP within 10 minutes, any privilege escalation event, after-hours administrative access (outside 07:00-19:00 ET Monday-Friday), and bulk data access exceeding 100 records in a single query. Monthly audit summary reports are prepared by the ISSO and provided to the Authorizing Official (AO). Annual audit review is documented in the Security Assessment Report. Log retention: 12 months active in CloudWatch, 3 years archived in S3 Glacier (WORM-configured via S3 Object Lock)."),
        ...controlBlock("AU-9", "Protection of Audit Information",
          "CloudWatch log groups are encrypted with AWS KMS (aws/logs managed key). IAM policies strictly limit log deletion and modification to break-glass accounts only (two individuals, requiring MFA for break-glass access). Log group retention policies prevent premature deletion. CloudTrail itself is protected: log file validation is enabled (SHA-256 hash chaining), CloudTrail logs stored in a separate dedicated S3 bucket with S3 Object Lock (WORM) enabled, and bucket access restricted to CloudTrail service principal and designated security accounts. Any attempt to disable CloudTrail generates an immediate GuardDuty finding and SNS alert."),
        ...controlBlock("AU-12", "Audit Record Generation",
          "Audit records are generated by the following components: (1) AWS ALB access logs (all HTTP/HTTPS requests, 5-minute delivery to S3); (2) Django application logging via Python logging framework, shipped to CloudWatch Logs via CloudWatch Agent; (3) PostgreSQL RDS audit logs via pgaudit extension (DDL, DML, connection events) shipped to CloudWatch; (4) S3 server access logs for all bucket operations; (5) AWS CloudTrail for all AWS API calls (management and data plane events for S3 and RDS); (6) VPC Flow Logs for all ENIs in the VPC. All log sources are synchronized to UTC via AWS Time Sync Service. Log completeness is verified monthly by querying correlation between ALB access logs and application-layer logs."),

        h3("1.5.3 Identification and Authentication (IA) Family"),
        ...controlBlock("IA-2", "Identification and Authentication — Organizational Users",
          "DCS staff authenticate to GovConnect Portal via the agency Active Directory (AD) federated to AWS IAM Identity Center using SAML 2.0. All staff logins require MFA via Okta Verify (TOTP). Privileged users (admins) are required to use hardware FIDO2 security keys (YubiKey 5 FIPS) for phishing-resistant MFA. Service accounts do not have interactive logins — they use IAM roles with EC2 instance profiles or Lambda execution roles. No long-term IAM access keys are used for service-to-service communication. Emergency break-glass accounts exist for disaster recovery, secured in a physical safe, and their use generates immediate alerts."),
        ...controlBlock("IA-3", "Device Identification and Authentication",
          "All server instances (EC2) are identified and managed via AWS Systems Manager (SSM). Each instance has an SSM-managed instance profile; instances without a valid instance profile cannot receive management commands or access Systems Manager Parameter Store. Device certificates are issued by the DCS internal PKI (CA hosted in AWS Private CA). Certificate-based authentication is used for VPN (Client VPN mutual TLS). Unmanaged or unregistered devices are blocked from accessing the VPC. No personal or unmanaged devices exist within the system boundary."),
        ...controlBlock("IA-5", "Authenticator Management",
          "Staff password requirements (enforced via Active Directory Group Policy): minimum 14 characters, must include uppercase, lowercase, number, and special character. Password expiration: 90 days. Password history: 10 previous passwords cannot be reused. Account lockout: 3 failed attempts (see AC-7). Citizens authenticate exclusively via Login.gov — GovConnect Portal does not store, manage, or handle citizen passwords or credentials. Staff passwords are stored by Active Directory using NTLM hash (PBKDF2 with SHA-256). Application-layer secrets (API keys, database credentials) are stored in AWS Secrets Manager with automatic 90-day rotation. No secrets are stored in code, configuration files, or environment variables."),
        ...controlBlock("IA-8", "Identification and Authentication — Non-Organizational Users",
          "Citizens (non-organizational users) authenticate via Login.gov, a FICAM-approved Credential Service Provider (CSP) operating at Identity Assurance Level 2 (IAL2) and Authenticator Assurance Level 2 (AAL2). Login.gov performs identity proofing (document verification and biometric comparison) and issues SAML assertions to GovConnect Portal. GovConnect does not perform identity proofing. Upon successful Login.gov authentication, GovConnect issues a session token (JWT, signed with RS256, 30-minute expiration, 30-minute inactivity timeout). Session tokens are transmitted via HTTPS only, set with Secure and HttpOnly flags, and stored server-side in Redis ElastiCache."),

        h3("1.5.4 System and Communications Protection (SC) Family"),
        ...controlBlock("SC-7", "Boundary Protection",
          "The system boundary is enforced through multiple defense-in-depth layers. Externally, AWS ALB accepts HTTPS traffic on port 443 only from the internet. AWS WAF is deployed on the ALB with the AWS Managed Rules — Core Rule Set (OWASP Top 10 protections), Amazon IP Reputation List, and custom rules for rate limiting (1,000 requests/minute per IP). Application instances reside in private subnets and are accessible only from the ALB security group. Database and cache instances reside in isolated data-tier subnets with no route to the internet gateway. VPC Flow Logs capture all network traffic. Network ACLs provide stateless filtering as a secondary control. All outbound internet access from application instances is routed through a NAT Gateway. Direct internet access to any component other than the ALB is blocked."),
        ...controlBlock("SC-8", "Transmission Confidentiality and Integrity",
          "All data in transit is encrypted using TLS 1.2 or higher. The ALB is configured with a security policy (ELBSecurityPolicy-TLS13-1-2-2021-06) that rejects TLS 1.0 and 1.1 connections. TLS 1.3 is preferred; TLS 1.2 is accepted for compatibility. The ALB SSL certificate is issued by Amazon Certificate Manager (ACM) and renewed automatically. Internal service-to-service communication (application to RDS, application to Redis) uses TLS with server certificate verification. RDS connections require SSL (ssl-mode=verify-full). S3 bucket policies deny all non-HTTPS PUT and GET requests. API Gateway endpoints enforce HTTPS only."),
        ...controlBlock("SC-28", "Protection of Information at Rest",
          "All data at rest is encrypted using AWS KMS customer-managed keys (CMKs). RDS PostgreSQL is encrypted with CMK DCS-RDS-Key. S3 buckets are encrypted with SSE-KMS using CMK DCS-S3-Key; bucket default encryption is enforced and bucket policies deny unencrypted PutObject operations. Redis ElastiCache is encrypted at rest using KMS. EC2 EBS volumes are encrypted with CMK DCS-EBS-Key; encrypted AMIs are used for all instance launches. KMS keys have automatic annual rotation enabled. CMK key policies restrict access to authorized IAM principals; all CMK usage is logged to CloudTrail. Key access is reviewed quarterly by the ISSO."),

        h3("1.5.5 System and Information Integrity (SI) Family"),
        ...controlBlock("SI-2", "Flaw Remediation",
          "Vulnerability remediation SLAs: Critical (CVSS 9.0+) within 15 calendar days; High (7.0-8.9) within 30 days; Medium (4.0-6.9) within 90 days; Low within 180 days. AWS Inspector runs continuously on EC2 instances and Lambda functions, reporting findings to Security Hub. Dependency vulnerability scanning is performed via Dependabot (GitHub) weekly for Python packages. OS patches are applied via AWS Systems Manager Patch Manager on a weekly schedule (maintenance window: Tuesday 02:00-04:00 UTC). Application deployments occur via CI/CD pipeline (GitHub Actions) with mandatory SAST (Semgrep) and SCA (Snyk) gate checks — deployments with Critical or High findings are blocked. Patch compliance status is reported to the AO monthly."),
        ...controlBlock("SI-3", "Malicious Code Protection",
          "AWS GuardDuty is enabled for all accounts in the DCS AWS Organization, providing continuous threat detection including malware detection on EC2 instances and S3 objects. AWS Inspector scans Lambda function packages for known malicious code signatures. All citizen-uploaded documents are scanned by a ClamAV integration (Lambda-based) before being stored to S3; files failing scan are quarantined in a separate S3 bucket and flagged for ISSO review. YARA rules are updated daily from the DCS threat intelligence feed. GuardDuty findings of MEDIUM severity or higher generate SNS notifications to the ISSO and Security Hub."),

        h3("1.5.6 Incident Response (IR) Family"),
        ...controlBlock("IR-4", "Incident Handling",
          "Incidents are classified by severity: Critical — confirmed data breach or system compromise affecting citizen PII/CUI (response SLA: 1 hour); High — suspected system compromise, unauthorized access, or significant availability impact (4 hours); Medium — anomalous behavior, policy violation with potential security impact (24 hours); Low — policy violation without security impact (5 business days). The IR team comprises: ISSO (incident lead), System Owner, AWS Enterprise Support (TAM), DCS Legal Counsel, and DCS Communications. All incidents are tracked in ServiceNow with mandatory fields: discovery time, reporter, affected systems, data involved, actions taken. US-CERT notification is required for confirmed incidents within 1 hour of determination. Post-incident reviews (PIRs) are mandatory for Critical and High incidents and must be completed within 5 business days."),

        h3("1.5.7 Contingency Planning (CP) Family"),
        ...controlBlock("CP-9", "System Backup",
          "Backup schedule and retention: RDS — automated snapshots daily (retained 35 days), transaction log backups every 5 minutes (point-in-time recovery to any point in the last 35 days). S3 — versioning enabled on all buckets, 30-day lifecycle for non-current versions, cross-region replication to DCS disaster recovery account (us-gov-east-1). EC2 — weekly AMI snapshots via AWS Backup (retained 90 days). All backups are stored in a separate AWS account (DCS-Backup-Prod) with cross-account access restricted to the backup service role. Recovery is tested quarterly; most recent test December 2025 — full system restoration achieved within the 4-hour RTO. RPO target: 15 minutes (achieved via RDS PITR and S3 versioning)."),
        new Paragraph({
          children: [],
          spacing: { after: 200 }
        }),

        // BACKUP SCHEDULE TABLE
        h2("1.6 Backup Schedule"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [1800, 2000, 2000, 1800, 1760],
          rows: [
            new TableRow({ children: [headerCell("Component", 1800), headerCell("Backup Type", 2000), headerCell("Frequency", 2000), headerCell("Retention", 1800), headerCell("Location", 1760)] }),
            new TableRow({ children: [cell("PostgreSQL RDS", 1800), cell("Automated Snapshot", 2000), cell("Daily", 2000), cell("35 days", 1800), cell("DCS-Backup-Prod", 1760)] }),
            new TableRow({ children: [cell("PostgreSQL RDS", 1800), cell("Transaction Log (PITR)", 2000), cell("Every 5 minutes", 2000), cell("35 days", 1800), cell("DCS-Backup-Prod", 1760)] }),
            new TableRow({ children: [cell("S3 (Documents)", 1800), cell("Versioning", 2000), cell("Continuous", 2000), cell("30 days (non-current)", 1800), cell("us-gov-east-1 (CRR)", 1760)] }),
            new TableRow({ children: [cell("EC2 AMIs", 1800), cell("AMI Snapshot (AWS Backup)", 2000), cell("Weekly", 2000), cell("90 days", 1800), cell("DCS-Backup-Prod", 1760)] }),
          ]
        }),

        pageBreak(),

        // ═════════════════════════════════════════════════════════════════════
        // SECTION 2 — INFORMATION SECURITY POLICY
        // ═════════════════════════════════════════════════════════════════════
        h1("2. Information Security Policy"),
        new Paragraph({
          children: [
            new TextRun({ text: "Policy Number: ", font: "Arial", size: 20, bold: true }),
            new TextRun({ text: "DCS-ISP-001", font: "Arial", size: 20 }),
            new TextRun({ text: "    Version: ", font: "Arial", size: 20, bold: true }),
            new TextRun({ text: "2.3", font: "Arial", size: 20 }),
            new TextRun({ text: "    Effective: ", font: "Arial", size: 20, bold: true }),
            new TextRun({ text: "January 15, 2026", font: "Arial", size: 20 }),
            new TextRun({ text: "    Review: ", font: "Arial", size: 20, bold: true }),
            new TextRun({ text: "January 15, 2027", font: "Arial", size: 20 }),
          ],
          spacing: { after: 80 }
        }),
        new Paragraph({
          children: [
            new TextRun({ text: "Approved By: ", font: "Arial", size: 20, bold: true }),
            new TextRun({ text: "Deputy Director Thomas Harrington", font: "Arial", size: 20 }),
          ],
          spacing: { after: 200 }
        }),

        h2("2.1 Purpose"),
        body("This policy establishes information security requirements for GovConnect Portal to protect citizen Personally Identifiable Information (PII) and Controlled Unclassified Information (CUI) in compliance with the Federal Information Security Modernization Act (FISMA), NIST SP 800-53 Rev 5, OMB Circular A-130, and Department of Citizen Services internal security standards. The policy supports the Department's mission to deliver secure, reliable citizen services while protecting sensitive government information from unauthorized disclosure, modification, or destruction."),

        h2("2.2 Scope"),
        body("This policy applies to all individuals and systems with access to GovConnect Portal, including:"),
        bullet("DCS employees in all roles (case workers, supervisors, administrators)"),
        bullet("Contractors and third-party vendors with authorized access"),
        bullet("All computing devices, applications, and infrastructure components within the GovConnect system boundary"),
        bullet("All data processed, stored, or transmitted by GovConnect Portal"),

        h2("2.3 Access Control Requirements"),
        bullet("All system access requires unique individual identifiers. Shared or group accounts are prohibited."),
        bullet("Privileged access requires written justification, Director-level approval, and quarterly access review."),
        bullet("Separation of duties is enforced: developers may not deploy to production without Change Advisory Board (CAB) approval and ISSO sign-off."),
        bullet("The principle of least privilege is enforced via RBAC; access is granted for the minimum necessary to perform job functions."),
        bullet("All remote access requires agency VPN plus MFA. Direct RDP/SSH from the internet is prohibited."),
        bullet("User access is reviewed quarterly by the ISSO against active HR records; excess access is revoked within 5 business days of review."),

        h2("2.4 Data Classification and Handling"),
        bullet("All CUI must be encrypted at rest (AES-256 minimum) and in transit (TLS 1.2+ minimum) at all times."),
        bullet("PII must not appear in log files in plaintext. PII fields must be masked, tokenized, or hashed before logging."),
        bullet("Data retention schedule: active benefit cases — 7 years; closed cases — 3 years; audit logs — 3 years minimum."),
        bullet("Media sanitization must follow NIST SP 800-88 Guidelines for Media Sanitization prior to disposal or reuse."),
        bullet("CUI must not be stored on personal devices, personal cloud storage, or non-DCS-approved systems."),
        bullet("All removable media containing CUI must be encrypted and approved by the ISSO before use."),

        h2("2.5 Incident Response Requirements"),
        bullet("All suspected security incidents must be reported to the ISSO (marcus.webb@dcs.gov) within 1 hour of discovery regardless of severity."),
        bullet("Confirmed incidents involving CUI or PII require US-CERT notification within 1 hour of confirmation per FISMA reporting requirements."),
        bullet("Digital evidence must be preserved in its original state before any remediation actions are taken. Chain of custody must be documented."),
        bullet("Post-incident reviews are mandatory for all Critical and High severity incidents. PIR must be completed within 5 business days and submitted to the AO."),
        bullet("Incident responders must document all actions taken in ServiceNow with timestamps to the minute."),

        h2("2.6 Acceptable Use"),
        bullet("GovConnect Portal system resources are authorized for official government business only."),
        bullet("Installation of software not pre-approved by the DCS IT department is prohibited on all government-owned assets."),
        bullet("Storage of government data (CUI, PII) on personal devices, personal email, or personal cloud services is strictly prohibited and may result in disciplinary action."),
        bullet("Users may not attempt to bypass, disable, or circumvent any security controls, monitoring systems, or access restrictions."),
        bullet("Any user who discovers a security vulnerability must report it to the ISSO immediately and must not exploit, share, or publicize the vulnerability."),

        h2("2.7 Enforcement"),
        body("Violations of this policy may result in disciplinary action up to and including termination, and may be referred to law enforcement authorities where criminal conduct is suspected. All users acknowledge this policy upon account provisioning and annually thereafter. The ISSO maintains signed policy acknowledgment records for all active users."),

        pageBreak(),

        // ═════════════════════════════════════════════════════════════════════
        // SECTION 3 — POA&M
        // ═════════════════════════════════════════════════════════════════════
        h1("3. Plan of Action and Milestones (POA&M)"),
        body("The following POA&M items represent known security control gaps identified during the most recent security review and continuous monitoring activities. Each item includes the affected control, finding description, risk rating, remediation plan, responsible party, and estimated completion date."),
        body("POA&M items are tracked in ServiceNow and reviewed monthly by the ISSO. Status updates are provided to the AO quarterly. Items are closed upon ISSO verification of remediation."),

        spacer(),

        // POA&M summary
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2340, 2340, 2340, 2340],
          rows: [
            new TableRow({ children: [headerCell("Total Open Items", 2340), headerCell("High Risk", 2340), headerCell("Medium Risk", 2340), headerCell("Low Risk", 2340)] }),
            new TableRow({ children: [shadeCell("3", 2340), new TableCell({
              width: { size: 2340, type: WidthType.DXA }, borders: allBorders("CCCCCC"), margins: { top: 80, bottom: 80, left: 120, right: 120 },
              shading: { fill: "C00000", type: ShadingType.CLEAR },
              children: [new Paragraph({ children: [new TextRun({ text: "1", font: "Arial", size: 18, bold: true, color: "FFFFFF" })] })]
            }), new TableCell({
              width: { size: 2340, type: WidthType.DXA }, borders: allBorders("CCCCCC"), margins: { top: 80, bottom: 80, left: 120, right: 120 },
              shading: { fill: ORANGE, type: ShadingType.CLEAR },
              children: [new Paragraph({ children: [new TextRun({ text: "1", font: "Arial", size: 18, bold: true, color: "FFFFFF" })] })]
            }), new TableCell({
              width: { size: 2340, type: WidthType.DXA }, borders: allBorders("CCCCCC"), margins: { top: 80, bottom: 80, left: 120, right: 120 },
              shading: { fill: "4472C4", type: ShadingType.CLEAR },
              children: [new Paragraph({ children: [new TextRun({ text: "1", font: "Arial", size: 18, bold: true, color: "FFFFFF" })] })]
            })] }),
          ]
        }),
        spacer(),

        // POA&M table
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [700, 1000, 2560, 600, 2400, 1100],
          rows: [
            new TableRow({
              children: [
                headerCell("ID", 700), headerCell("Control", 1000), headerCell("Finding", 2560),
                headerCell("Risk", 600), headerCell("Remediation Plan", 2400), headerCell("Owner / ETA", 1100)
              ]
            }),
            poamRow(
              "POA-001", "AC-11\nSession Lock",
              "The citizen portal does not enforce an automatic session lock with re-authentication prompt for shared or kiosk environments. Current implementation silently terminates the session after 30-minute inactivity and redirects to the login page, which does not meet AC-11 requirements for session lock with re-authentication.",
              "MED", ORANGE,
              "Implement a 5-minute idle warning dialog followed by a session lock screen requiring re-authentication before resuming. Replace silent session termination with explicit lock-and-resume flow.",
              "Marcus Webb (ISSO)\nQ2 2026"
            ),
            poamRow(
              "POA-002", "IA-11\nRe-authentication",
              "The system does not enforce step-up re-authentication for high-risk functions including modification of bank account information for direct deposit. Sessions authenticated more than 4 hours ago can access these functions without re-verification, creating risk of session hijacking leading to financial fraud.",
              "HIGH", RED,
              "Implement step-up authentication via Login.gov IAL2 re-verification for all transactions modifying financial data, identity documents, or contact information. Re-authentication required if session age exceeds 1 hour. Development complete; pending security testing.",
              "Sarah Chen (Dev Lead)\nQ1 2026 (In Progress)"
            ),
            poamRow(
              "POA-003", "CM-11\nUser-Installed Software",
              "Lambda execution environment lacks explicit technical controls preventing runtime pip install of unapproved packages. While the Lambda execution IAM role is restricted, a compromised Lambda function could install malicious packages during execution, bypassing the approved software baseline.",
              "LOW", "4472C4",
              "Pin all dependencies to specific SHA256-verified Lambda Layers. Configure Lambda runtime with read-only root filesystem to prevent runtime package installation. Add Lambda layer integrity verification to CI/CD pipeline pre-deployment checks.",
              "Cloud Infra Team\nQ3 2026"
            ),
          ]
        }),

        spacer(),
        h2("3.1 POA&M Review Schedule"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2340, 2340, 2340, 2340],
          rows: [
            new TableRow({ children: [headerCell("Activity", 2340), headerCell("Frequency", 2340), headerCell("Responsible", 2340), headerCell("Deliverable", 2340)] }),
            new TableRow({ children: [cell("Status Update", 2340), cell("Monthly", 2340), cell("ISSO", 2340), cell("ServiceNow ticket update", 2340)] }),
            new TableRow({ children: [cell("AO Briefing", 2340), cell("Quarterly", 2340), cell("ISSO + System Owner", 2340), cell("POA&M Status Report", 2340)] }),
            new TableRow({ children: [cell("Closure Verification", 2340), cell("Upon remediation", 2340), cell("ISSO", 2340), cell("Evidence package in ServiceNow", 2340)] }),
            new TableRow({ children: [cell("Annual Rollup Review", 2340), cell("Annual", 2340), cell("ISSO + AO", 2340), cell("Security Assessment Report update", 2340)] }),
          ]
        }),

        spacer(),
        h2("3.2 Residual Risk Acceptance"),
        body("The System Owner and Authorizing Official acknowledge that POA-001 (AC-11 Session Lock) and POA-003 (CM-11 User-Installed Software) represent accepted residual risk pending remediation. Interim compensating controls are in place: for POA-001, sessions timeout after 30 minutes of inactivity which limits exposure; for POA-003, Lambda execution roles are strictly limited and CloudTrail monitors all Lambda invocations. POA-002 (IA-11 Re-authentication) is in active remediation with an expected closure date of Q1 2026."),

        spacer(),
        new Paragraph({
          children: [new TextRun({ text: "— END OF DOCUMENT —", font: "Arial", size: 20, bold: true, color: "888888" })],
          alignment: AlignmentType.CENTER,
          spacing: { before: 400, after: 400 }
        }),
        new Paragraph({
          children: [new TextRun({ text: "CUI // FOR OFFICIAL USE ONLY", font: "Arial", size: 18, bold: true, color: RED })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 }
        }),
        new Paragraph({
          children: [new TextRun({ text: "GovConnect Portal ATO Package v1.0 | DCS-ATO-001 | March 2026", font: "Arial", size: 16, color: "888888" })],
          alignment: AlignmentType.CENTER
        }),
      ]
    }
  ]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync('GovConnect_ATO_Package_v1.docx', buffer);
  console.log('SUCCESS: GovConnect_ATO_Package_v1.docx created (' + (buffer.length / 1024).toFixed(0) + ' KB)');
});
