import type { Conversation, ChatMessage, Citation } from "@/types";

/**
 * Mock chat conversations and messages with citations for RAG responses
 */

// Sample citations
const citation1: Citation = {
  id: "cite-1",
  documentId: "doc-1",
  documentTitle: "COMMON Module 3 Characteristics of LNG",
  sectionHeading: "3. Physical Properties of LNG",
  pageNumber: 12,
  excerpt:
    "LNG density at atmospheric pressure is approximately 450 kg/m³ at -162°C. This density varies with composition and temperature...",
  relevanceScore: 0.94,
};

const citation2: Citation = {
  id: "cite-2",
  documentId: "doc-2",
  documentTitle: "Cryogenic Pump System Operating Manual",
  sectionHeading: "3.1 Emergency Response",
  pageNumber: 15,
  excerpt:
    "In case of LNG spill: Activate emergency alarm, evacuate non-essential personnel to upwind locations, do NOT use water on LNG spills...",
  relevanceScore: 0.91,
};

const citation3: Citation = {
  id: "cite-3",
  documentId: "doc-1",
  documentTitle: "COMMON Module 3 Characteristics of LNG",
  sectionHeading: "2.4 Boil-Off Gas Management",
  pageNumber: 8,
  excerpt:
    "Normal boil-off rate for insulated LNG storage is 0.05-0.1% per day. BOG must be managed through either reliquefaction or fuel gas systems...",
  relevanceScore: 0.88,
};

const citation4: Citation = {
  id: "cite-4",
  documentId: "doc-2",
  documentTitle: "Cryogenic Pump System Operating Manual",
  sectionHeading: "4.2 Normal Startup Sequence",
  pageNumber: 21,
  excerpt:
    "Cool-down procedure: Slowly introduce LNG to pump casing. Monitor temperature differential (<50°C/hr cooling rate). Allow 4-6 hours for complete thermal stabilization...",
  relevanceScore: 0.96,
};

const citation5: Citation = {
  id: "cite-5",
  documentId: "doc-6",
  documentTitle: "Instrumentation Calibration Standards",
  sectionHeading: "5.2 Pressure Transmitter Calibration",
  pageNumber: 34,
  excerpt:
    "Pressure transmitters shall be calibrated at 0%, 25%, 50%, 75%, and 100% of span in both ascending and descending directions. Maximum allowable error: ±0.25% of span...",
  relevanceScore: 0.92,
};

// Sample conversation 1
const conversation1Messages: ChatMessage[] = [
  {
    id: "msg-1-1",
    role: "user",
    content: "What is the density of LNG?",
    timestamp: "2026-02-19T08:30:00Z",
  },
  {
    id: "msg-1-2",
    role: "assistant",
    content:
      "LNG (Liquefied Natural Gas) has a density of approximately **450 kg/m³** at atmospheric pressure and -162°C. It's important to note that this density can vary depending on the composition of the natural gas and the exact temperature.\n\nThis relatively low density compared to water (which has a density of 1000 kg/m³) means that LNG will float on water if spilled, which is an important consideration for spill response and facility design.",
    timestamp: "2026-02-19T08:30:02Z",
    citations: [citation1],
  },
  {
    id: "msg-1-3",
    role: "user",
    content: "What should I do if there's an LNG spill?",
    timestamp: "2026-02-19T08:31:15Z",
  },
  {
    id: "msg-1-4",
    role: "assistant",
    content:
      "In case of an LNG spill, follow these critical emergency response steps:\n\n**Immediate Actions:**\n1. **Activate the emergency alarm** to alert all facility personnel\n2. **Evacuate non-essential personnel** to upwind locations (LNG vapor is heavier than air and will flow to low areas)\n3. **DO NOT use water** on LNG spills - this causes rapid vaporization and creates additional hazards\n4. **Allow controlled evaporation** in open, well-ventilated areas\n5. **Monitor the vapor cloud** using gas detectors to track flammable gas concentrations\n\n**Critical Safety Note:** Direct contact with LNG or cryogenic surfaces can cause severe cold burns and frostbite. Always ensure you're wearing appropriate PPE including cryogenic gloves (rated to -162°C), face shield, and insulated safety boots before approaching the area.\n\nRefer to your facility's Emergency Response Plan for detailed site-specific procedures and emergency contact numbers.",
    timestamp: "2026-02-19T08:31:18Z",
    citations: [citation2],
  },
  {
    id: "msg-1-5",
    role: "user",
    content: "What's the typical boil-off rate for LNG storage?",
    timestamp: "2026-02-19T08:33:00Z",
  },
  {
    id: "msg-1-6",
    role: "assistant",
    content:
      "For insulated LNG storage tanks, the normal boil-off rate is approximately **0.05-0.1% per day**. This represents the amount of LNG that naturally evaporates due to heat ingress through the tank insulation.\n\nThis boil-off gas (BOG) must be actively managed through one of two methods:\n- **Reliquefaction**: Cooling and compressing the BOG back to liquid state\n- **Fuel gas systems**: Using the BOG as fuel for facility equipment such as gas turbines or boilers\n\nProper BOG management is critical for both economic reasons (minimizing product loss) and safety (preventing overpressure in storage tanks).",
    timestamp: "2026-02-19T08:33:03Z",
    citations: [citation3],
  },
];

// Sample conversation 2
const conversation2Messages: ChatMessage[] = [
  {
    id: "msg-2-1",
    role: "user",
    content: "How do I start up the cryogenic pump?",
    timestamp: "2026-02-19T09:15:00Z",
  },
  {
    id: "msg-2-2",
    role: "assistant",
    content:
      "The cryogenic pump startup procedure must be followed carefully to prevent thermal shock damage. Here's the normal startup sequence:\n\n**Step 1: Cool-down Procedure**\n- Slowly introduce LNG to the pump casing\n- Monitor the temperature differential (must be less than 50°C/hr cooling rate)\n- Allow **4-6 hours** for complete thermal stabilization\n\n**Step 2: Motor Energization**\n- Verify rotation direction (should be counter-clockwise)\n- Start the motor in no-load condition\n- Monitor vibration levels and bearing temperatures\n\n**Step 3: Flow Establishment**\n- Slowly open the discharge valve in 10% increments\n- Monitor pump discharge pressure and flow rate\n- Verify performance against the pump curve\n\n**Step 4: Transfer to Automatic Control**\n- Enable PID flow control\n- Set target flow setpoint\n- Monitor for stable operation\n\n**Before starting**, ensure you've completed the pre-startup checklist including verifying LNG level in pump pit, confirming nitrogen seal gas pressure (5-7 bar), and checking that all safety interlocks are functional.",
    timestamp: "2026-02-19T09:15:04Z",
    citations: [citation4],
  },
];

// Sample conversation 3
const conversation3Messages: ChatMessage[] = [
  {
    id: "msg-3-1",
    role: "user",
    content: "What are the calibration requirements for pressure transmitters?",
    timestamp: "2026-02-19T10:00:00Z",
  },
  {
    id: "msg-3-2",
    role: "assistant",
    content:
      "Pressure transmitters must be calibrated according to the following standards:\n\n**Calibration Points:**\n- Test at 0%, 25%, 50%, 75%, and 100% of the instrument span\n- Perform calibration in both **ascending** and **descending** directions (to check for hysteresis)\n\n**Acceptance Criteria:**\n- Maximum allowable error: **±0.25% of span**\n- This is the permitted deviation from the actual pressure at any calibration point\n\n**Documentation:**\n- Record all calibration data including as-found and as-left conditions\n- Document any adjustments made\n- Attach calibration certificate to instrument file\n\n**Frequency:**\nRefer to Section 5.2 of the Instrumentation Calibration Standards for recommended calibration intervals based on service criticality and process conditions.",
    timestamp: "2026-02-19T10:00:03Z",
    citations: [citation5],
  },
];

export const mockConversations: Conversation[] = [
  {
    id: "conv-1",
    userId: "user-1",
    title: "LNG Properties and Spill Response",
    messages: conversation1Messages,
    createdAt: "2026-02-19T08:30:00Z",
    updatedAt: "2026-02-19T08:33:03Z",
  },
  {
    id: "conv-2",
    userId: "user-1",
    title: "Cryogenic Pump Startup",
    messages: conversation2Messages,
    createdAt: "2026-02-19T09:15:00Z",
    updatedAt: "2026-02-19T09:15:04Z",
  },
  {
    id: "conv-3",
    userId: "user-2",
    title: "Pressure Transmitter Calibration",
    messages: conversation3Messages,
    createdAt: "2026-02-19T10:00:00Z",
    updatedAt: "2026-02-19T10:00:03Z",
  },
];

/**
 * Helper to get or create conversation for a user
 */
export function getUserConversation(userId: string): Conversation {
  const existing = mockConversations.find((c) => c.userId === userId);
  if (existing) return existing;

  // Return empty new conversation
  return {
    id: `conv-new-${Date.now()}`,
    userId,
    title: "New Conversation",
    messages: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

/**
 * Get the current active conversation (most recent)
 */
export function getActiveConversation(userId: string): Conversation {
  const userConversations = mockConversations.filter((c) => c.userId === userId);
  if (userConversations.length === 0) {
    return getUserConversation(userId);
  }
  // Return most recently updated
  return userConversations.sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  )[0];
}
