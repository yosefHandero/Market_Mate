import { Inngest} from "inngest";

export const inngest = new Inngest({
    id: 'Market_Mate',
    ai: process.env.GEMINI_API_KEY ? { gemini: { apiKey: process.env.GEMINI_API_KEY } } : undefined
})
