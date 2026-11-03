import fs from "node:fs";
import path from "node:path";

import dotenv from "dotenv";

/** 脚本跑在 Next.js 之外，需要自己加载 .env.local（Next 会自动加载，独立脚本不会）。 */
for (const file of [".env.local", ".env"]) {
  const filePath = path.resolve(process.cwd(), file);
  if (fs.existsSync(filePath)) {
    dotenv.config({ path: filePath });
  }
}
