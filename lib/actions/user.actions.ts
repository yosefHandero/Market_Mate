'use server';

import {connectToDatabase} from "@/database/mongoose";

export type UserForNewsEmail = {
    id: string;
    email: string;
    name: string;
};

export const getAllUsersForNewsEmail = async (): Promise<UserForNewsEmail[]> => {
    try {
        const mongoose = await connectToDatabase();
        const db = mongoose.connection.db;
        if(!db) throw new Error('Mongoose connection not connected');

        const users = await db.collection('user').find(
            { email: { $exists: true, $ne: null }},
            { projection: { _id: 1, id: 1, email: 1, name: 1, country:1 }}
        ).toArray();

        return users
            .filter((user) => user.email && user.name)
            .map((user) => ({
                id: user.id || user._id?.toString() || '',
                email: user.email as string,
                name: user.name as string,
            }))
    } catch (e) {
        console.error('Error fetching users for news email:', e)
        return []
    }
}
