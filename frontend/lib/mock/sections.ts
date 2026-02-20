import type { DocumentSection, ReviewChecklist, SectionVersion } from "@/types";

/**
 * Mock document sections for the review interface
 */

// Helper to create default checklist
const createDefaultChecklist = (overrides?: Partial<ReviewChecklist>): ReviewChecklist => ({
  textAccuracyConfirmed: false,
  tablesVerified: false,
  imagesDescribed: false,
  formattingCorrect: false,
  technicalTermsAccurate: false,
  ...overrides,
});

// Mock sections for doc-2 (Cryogenic Pump System - in review)
export const mockSections: DocumentSection[] = [
  {
    id: "section-2-1",
    documentId: "doc-2",
    sectionNumber: 1,
    heading: "1. Introduction to Cryogenic Pumping Systems",
    content: `# 1. Introduction to Cryogenic Pumping Systems\n\nCryogenic pumps are specialized devices designed to handle liquefied natural gas (LNG) at temperatures as low as -162°C (-260°F). These pumps must maintain structural integrity and operational reliability under extreme thermal stress.\n\n## 1.1 Purpose\n\nThis manual provides comprehensive guidance for operating, maintaining, and troubleshooting cryogenic pump systems installed at LNG processing facilities.\n\n## 1.2 Scope\n\nThe manual covers:\n- System overview and operating principles\n- Safety procedures and precautions\n- Startup and shutdown sequences\n- Routine maintenance schedules\n- Troubleshooting common issues`,
    status: "complete",
    checklist: createDefaultChecklist({
      textAccuracyConfirmed: true,
      tablesVerified: true,
      imagesDescribed: true,
      formattingCorrect: true,
      technicalTermsAccurate: true,
    }),
    evidenceImages: ["/mock-evidence/doc2-page1.png", "/mock-evidence/doc2-page2.png"],
    pageRange: { start: 1, end: 3 },
    currentVersion: {
      content: "Current version content...",
      timestamp: "2026-02-18T10:00:00Z",
      reviewedBy: "Mike Chen",
    },
    lastApprovedVersion: {
      content: "Last approved version content...",
      timestamp: "2026-02-17T15:30:00Z",
      reviewedBy: "Laura Garcia",
    },
    issues: [],
  },
  {
    id: "section-2-2",
    documentId: "doc-2",
    sectionNumber: 2,
    heading: "2. System Components and Specifications",
    content: `# 2. System Components and Specifications\n\n## 2.1 Main Pump Assembly\n\nThe cryogenic pump system consists of:\n- **Submerged motor pump unit**: Designed for direct LNG immersion\n- **Thermal insulation jacket**: Multi-layer vacuum insulation\n- **Shaft seal system**: Triple mechanical seal with nitrogen buffer\n- **Bearing assembly**: Self-lubricating ceramic bearings\n\n## 2.2 Performance Specifications\n\n| Parameter | Value | Unit |\n|-----------|-------|------|\n| Flow Rate (Design) | 500 | m³/h |\n| Discharge Pressure | 85 | bar |\n| Operating Temperature | -162 | °C |\n| Motor Power | 250 | kW |\n| Efficiency | 78 | % |\n\n> **Note**: All specifications are at design conditions. Actual performance may vary based on operating conditions.`,
    status: "in-review",
    checklist: createDefaultChecklist({
      textAccuracyConfirmed: true,
      tablesVerified: false, // Table needs verification
      formattingCorrect: true,
    }),
    evidenceImages: [
      "/mock-evidence/doc2-page4.png",
      "/mock-evidence/doc2-page5.png",
      "/mock-evidence/doc2-page6.png",
    ],
    pageRange: { start: 4, end: 8 },
    currentVersion: {
      content: "Current version...",
      timestamp: "2026-02-19T08:30:00Z",
      reviewedBy: "Mike Chen",
    },
    issues: [],
  },
  {
    id: "section-2-3",
    documentId: "doc-2",
    sectionNumber: 3,
    heading: "3. Safety Procedures and Precautions",
    content: `# 3. Safety Procedures and Precautions\n\n⚠️ **WARNING: CRYOGENIC HAZARDS**\n\nDirect contact with LNG or cryogenic equipment surfaces can cause severe cold burns and frostbite. Always wear appropriate PPE:\n- Cryogenic gloves (rated to -162°C)\n- Face shield\n- Insulated safety boots\n- Cold weather clothing\n\n## 3.1 Emergency Response\n\nIn case of LNG spill:\n1. **Activate emergency alarm**\n2. **Evacuate non-essential personnel** to upwind locations\n3. **Do NOT use water** on LNG spills - rapid vaporization creates hazard\n4. **Allow controlled evaporation** in open areas\n5. **Monitor vapor cloud** with gas detectors\n\n## 3.2 Confined Space Entry\n\n**NEVER enter pump pit or confined spaces** without:\n- Valid confined space entry permit\n- Atmospheric monitoring (O₂, LEL, toxics)\n- Continuous ventilation\n- Standby rescue personnel`,
    status: "in-review",
    checklist: createDefaultChecklist({
      textAccuracyConfirmed: true,
      formattingCorrect: true,
    }),
    evidenceImages: [
      "/mock-evidence/doc2-page9.png",
      "/mock-evidence/doc2-page10.png",
      "/mock-evidence/doc2-page15.png",
    ],
    pageRange: { start: 9, end: 18 },
    currentVersion: {
      content: "Current version...",
      timestamp: "2026-02-19T09:15:00Z",
      reviewedBy: "Mike Chen",
    },
    issues: [
      {
        id: "issue-4",
        page: 15,
        category: "missing-text",
        severity: "high",
        description: "Safety warning callout box text not fully extracted",
        evidenceImageUrl: "/mock-evidence/doc2-page15.png",
        context: "WARNING: Low Temperature Hazards",
      },
    ],
  },
  {
    id: "section-2-4",
    documentId: "doc-2",
    sectionNumber: 4,
    heading: "4. Startup and Shutdown Procedures",
    content: `# 4. Startup and Shutdown Procedures\n\n## 4.1 Pre-Startup Checklist\n\nBefore initiating pump startup:\n- [ ] Verify LNG level in pump pit\n- [ ] Confirm nitrogen seal gas pressure (5-7 bar)\n- [ ] Check motor cooling system operational\n- [ ] Verify discharge valve closed\n- [ ] Confirm all instrumentation functional\n- [ ] Review safety interlocks status\n\n## 4.2 Normal Startup Sequence\n\n**Step 1**: Cool-down procedure\n- Slowly introduce LNG to pump casing\n- Monitor temperature differential (<50°C/hr cooling rate)\n- Allow 4-6 hours for complete thermal stabilization\n\n**Step 2**: Motor energization\n- Verify rotation direction (counter-clockwise)\n- Start motor in no-load condition\n- Monitor vibration and bearing temperatures\n\n**Step 3**: Flow establishment\n- Slowly open discharge valve in 10% increments\n- Monitor pump discharge pressure and flow\n- Verify performance against curve\n\n**Step 4**: Transfer to automatic control\n- Enable PID flow control\n- Set target flow setpoint\n- Monitor for stable operation`,
    status: "draft",
    checklist: createDefaultChecklist(),
    evidenceImages: [
      "/mock-evidence/doc2-page19.png",
      "/mock-evidence/doc2-page20.png",
      "/mock-evidence/doc2-page21.png",
    ],
    pageRange: { start: 19, end: 28 },
    currentVersion: {
      content: "Current draft...",
      timestamp: "2026-02-19T10:00:00Z",
    },
    issues: [],
  },
];

/**
 * Mock sections for doc-3 (Emergency Shutdown System P&ID - ready for review)
 */
export const doc3Sections: DocumentSection[] = [
  {
    id: "section-3-1",
    documentId: "doc-3",
    sectionNumber: 1,
    heading: "1. Emergency Shutdown System Overview",
    content: `# 1. Emergency Shutdown System Overview\n\nThe Emergency Shutdown (ESD) system provides automated protection for the LNG facility in response to hazardous conditions. The system utilizes redundant safety instrumented functions (SIF) rated to SIL 3 per IEC 61511.\n\n## 1.1 System Architecture\n\nThe ESD system comprises:\n- Triple-redundant logic solvers (2oo3 voting)\n- Fail-safe field instrumentation\n- Double block and bleed isolation valves\n- Emergency depressurization systems`,
    status: "draft",
    checklist: createDefaultChecklist(),
    evidenceImages: ["/mock-evidence/doc3-page1.png"],
    pageRange: { start: 1, end: 2 },
    currentVersion: {
      content: "Current version...",
      timestamp: "2026-02-19T07:00:00Z",
    },
    issues: [],
  },
];

/**
 * Helper function to get sections by document ID
 */
export function getSectionsByDocId(documentId: string): DocumentSection[] {
  if (documentId === "doc-2") return mockSections;
  if (documentId === "doc-3") return doc3Sections;
  return [];
}

/**
 * Helper function to get section by ID
 */
export function getSectionById(sectionId: string): DocumentSection | undefined {
  return [...mockSections, ...doc3Sections].find((s) => s.id === sectionId);
}

/**
 * Helper to calculate review progress percentage
 */
export function calculateReviewProgress(sections: DocumentSection[]): number {
  if (sections.length === 0) return 0;
  const completeSections = sections.filter((s) => s.status === "complete").length;
  return Math.round((completeSections / sections.length) * 100);
}
