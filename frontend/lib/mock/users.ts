import type { User } from "@/types";

/**
 * Mock user data for authentication and role-based access control
 */

export const mockUsers: User[] = [
  {
    id: "user-1",
    username: "jdoe",
    email: "john.doe@bhegts.com",
    fullName: "John Doe",
    role: "user",
    lastLogin: "2026-02-19T06:45:00Z",
    status: "active",
    department: "Operations",
  },
  {
    id: "user-2",
    username: "ssmith",
    email: "sarah.smith@bhegts.com",
    fullName: "Sarah Smith",
    role: "user",
    lastLogin: "2026-02-19T05:30:00Z",
    status: "active",
    department: "Maintenance",
  },
  {
    id: "admin-1",
    username: "rholt",
    email: "randy.holt@bhegts.com",
    fullName: "Randy Holt",
    role: "admin",
    lastLogin: "2026-02-19T06:00:00Z",
    status: "active",
    department: "Operations Management",
  },
  {
    id: "admin-2",
    username: "awilliams",
    email: "alex.williams@bhegts.com",
    fullName: "Alex Williams",
    role: "admin",
    lastLogin: "2026-02-17T16:45:00Z",
    status: "active",
    department: "IT/OT Infrastructure",
  },
  {
    id: "user-3",
    username: "bjohnson",
    email: "bob.johnson@bhegts.com",
    fullName: "Bob Johnson",
    role: "user",
    lastLogin: null,
    status: "disabled",
    department: "Operations",
  },
];

/**
 * Helper function to find user by username
 */
export function getUserByUsername(username: string): User | undefined {
  return mockUsers.find((u) => u.username === username);
}

/**
 * Helper function to get users by role
 */
export function getUsersByRole(role: User["role"]): User[] {
  return mockUsers.filter((u) => u.role === role);
}
