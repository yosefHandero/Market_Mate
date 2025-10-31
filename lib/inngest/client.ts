import { Inngest} from "inngest";

export const inngest = new Inngest({
    id: 'Market_Mate',
    ai: { gemini: { apiKey: process.env.GEMINI_API_KEY! }}
})
