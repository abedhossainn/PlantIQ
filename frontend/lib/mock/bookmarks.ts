import type { Bookmark } from "@/types";

/**
 * Mock bookmarked answers for quick reference
 *
 * Fixture goals:
 * - Validate bookmark list rendering with markdown answers and citations.
 * - Cover multiple tags and note combinations for filtering UX.
 * - Provide varied query/answer lengths to test card responsiveness.
 *
 * Operational realism:
 * - Uses LNG procedure-oriented prompts representative of field usage.
 * - Keeps citation payloads aligned with chat fixture documents.
 */

export const mockBookmarks: Bookmark[] = [
  {
    id: "bookmark-1",
    userId: "user-1",
    conversationId: "conv-1",
    messageId: "msg-1-4",
    query: "What should I do if there's an LNG spill?",
    answer:
      "In case of an LNG spill, follow these critical emergency response steps:\n\n**Immediate Actions:**\n1. **Activate the emergency alarm** to alert all facility personnel\n2. **Evacuate non-essential personnel** to upwind locations (LNG vapor is heavier than air and will flow to low areas)\n3. **DO NOT use water** on LNG spills - this causes rapid vaporization and creates additional hazards\n4. **Allow controlled evaporation** in open, well-ventilated areas\n5. **Monitor the vapor cloud** using gas detectors to track flammable gas concentrations...",
    citations: [
      {
        id: "cite-2",
        documentId: "doc-2",
        documentTitle: "Cryogenic Pump System Operating Manual",
        sectionHeading: "3.1 Emergency Response",
        pageNumber: 15,
        excerpt:
          "In case of LNG spill: Activate emergency alarm, evacuate non-essential personnel to upwind locations, do NOT use water on LNG spills...",
        relevanceScore: 0.91,
      },
    ],
    createdAt: "2026-02-19T08:32:00Z",
    tags: ["emergency", "safety", "spill-response"],
    notes: "Critical safety procedure - review before each shift",
  },
  {
    id: "bookmark-2",
    userId: "user-1",
    conversationId: "conv-2",
    messageId: "msg-2-2",
    query: "How do I start up the cryogenic pump?",
    answer:
      "The cryogenic pump startup procedure must be followed carefully to prevent thermal shock damage. Here's the normal startup sequence:\n\n**Step 1: Cool-down Procedure**\n- Slowly introduce LNG to the pump casing\n- Monitor the temperature differential (must be less than 50°C/hr cooling rate)\n- Allow **4-6 hours** for complete thermal stabilization...",
    citations: [
      {
        id: "cite-4",
        documentId: "doc-2",
        documentTitle: "Cryogenic Pump System Operating Manual",
        sectionHeading: "4.2 Normal Startup Sequence",
        pageNumber: 21,
        excerpt:
          "Cool-down procedure: Slowly introduce LNG to pump casing. Monitor temperature differential (<50°C/hr cooling rate). Allow 4-6 hours for complete thermal stabilization...",
        relevanceScore: 0.96,
      },
    ],
    createdAt: "2026-02-19T09:16:30Z",
    tags: ["pump", "startup", "procedure"],
    notes: "Reference for pump A startup next week",
  },
  {
    id: "bookmark-3",
    userId: "user-2",
    conversationId: "conv-3",
    messageId: "msg-3-2",
    query: "What are the calibration requirements for pressure transmitters?",
    answer:
      "Pressure transmitters must be calibrated according to the following standards:\n\n**Calibration Points:**\n- Test at 0%, 25%, 50%, 75%, and 100% of the instrument span\n- Perform calibration in both **ascending** and **descending** directions (to check for hysteresis)\n\n**Acceptance Criteria:**\n- Maximum allowable error: **±0.25% of span**...",
    citations: [
      {
        id: "cite-5",
        documentId: "doc-6",
        documentTitle: "Instrumentation Calibration Standards",
        sectionHeading: "5.2 Pressure Transmitter Calibration",
        pageNumber: 34,
        excerpt:
          "Pressure transmitters shall be calibrated at 0%, 25%, 50%, 75%, and 100% of span in both ascending and descending directions. Maximum allowable error: ±0.25% of span...",
        relevanceScore: 0.92,
      },
    ],
    createdAt: "2026-02-19T10:02:00Z",
    tags: ["calibration", "instrumentation", "maintenance"],
    notes: "Need for monthly calibration work",
  },
  {
    id: "bookmark-4",
    userId: "user-1",
    conversationId: "conv-1",
    messageId: "msg-1-2",
    query: "What is the density of LNG?",
    answer:
      "LNG (Liquefied Natural Gas) has a density of approximately **450 kg/m³** at atmospheric pressure and -162°C. It's important to note that this density can vary depending on the composition of the natural gas and the exact temperature.\n\nThis relatively low density compared to water (which has a density of 1000 kg/m³) means that LNG will float on water if spilled, which is an important consideration for spill response and facility design.",
    citations: [
      {
        id: "cite-1",
        documentId: "doc-1",
        documentTitle: "COMMON Module 3 Characteristics of LNG",
        sectionHeading: "3. Physical Properties of LNG",
        pageNumber: 12,
        excerpt:
          "LNG density at atmospheric pressure is approximately 450 kg/m³ at -162°C. This density varies with composition and temperature...",
        relevanceScore: 0.94,
      },
    ],
    createdAt: "2026-02-19T08:31:00Z",
    tags: ["properties", "density", "lng"],
  },
];

/**
 * Helper to get bookmarks for a user
 */
export function getBookmarksByUserId(userId: string): Bookmark[] {
  return mockBookmarks.filter((b) => b.userId === userId);
}

/**
 * Helper to get bookmark by ID
 */
export function getBookmarkById(id: string): Bookmark | undefined {
  return mockBookmarks.find((b) => b.id === id);
}

/**
 * Helper to check if a message is bookmarked
 */
export function isMessageBookmarked(userId: string, messageId: string): boolean {
  return mockBookmarks.some((b) => b.userId === userId && b.messageId === messageId);
}
