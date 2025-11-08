import { NextRequest, NextResponse } from 'next/server';

import type { Types } from 'mongoose';
import { connectToDatabase } from "@/database/mongoose";
import { Watchlist, type WatchlistItem } from "@/database/models/watchlist.model";
import { getCurrentUserFromHeaders } from "@/lib/auth/session";

const UNAUTHORIZED_RESPONSE = NextResponse.json(
  { success: false, error: 'Unauthorized' },
  { status: 401 }
);

type WatchlistPayload = {
  symbol?: string;
  company?: string;
};

type WatchlistRecord = {
  _id: Types.ObjectId;
  symbol: string;
  company?: string | null;
  createdAt?: Date | string;
  addedAt?: Date | string;
};

export async function GET(request: NextRequest) {
  const user = await getCurrentUserFromHeaders(request.headers);

  if (!user) {
    return UNAUTHORIZED_RESPONSE;
  }

  await connectToDatabase();

  const items = await Watchlist.find<WatchlistRecord>({ userId: user.id })
    .sort({ createdAt: -1 })
    .lean();

  const data = items.map((item) => {
    const createdAtValue = item.createdAt ?? item.addedAt ?? new Date();
    const createdAtDate = createdAtValue instanceof Date ? createdAtValue : new Date(createdAtValue);

    return {
      id: item._id.toString(),
      symbol: item.symbol,
      company: item.company ?? item.symbol,
      createdAt: createdAtDate.toISOString(),
    };
  });

  return NextResponse.json({ success: true, data });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUserFromHeaders(request.headers);

  if (!user) {
    return UNAUTHORIZED_RESPONSE;
  }

  const body = (await request.json().catch(() => ({}))) as WatchlistPayload;
  const symbol = body.symbol?.trim().toUpperCase();

  if (!symbol) {
    return NextResponse.json({ success: false, error: 'Symbol is required' }, { status: 400 });
  }

  await connectToDatabase();

  const company = body.company?.trim() || symbol;

  const existing = await Watchlist.findOne({ userId: user.id, symbol });

  if (existing) {
    const existingObj = existing.toObject<WatchlistRecord & WatchlistItem>();
    const createdAtValue = existingObj.createdAt ?? existingObj.addedAt ?? new Date();

    return NextResponse.json({
      success: true,
      data: {
        id: existing._id.toString(),
        symbol: existing.symbol,
        company: existing.company ?? existing.symbol,
        createdAt: createdAtValue instanceof Date ? createdAtValue.toISOString() : new Date(createdAtValue).toISOString(),
      },
    });
  }

  const created = await Watchlist.create({
    userId: user.id,
    symbol,
    company,
  });

  const createdObj = created.toObject<WatchlistRecord & WatchlistItem>();
  const createdAtValue = createdObj.createdAt ?? new Date();

  return NextResponse.json(
    {
      success: true,
      data: {
        id: created._id.toString(),
        symbol: created.symbol,
        company: created.company ?? created.symbol,
        createdAt: createdAtValue instanceof Date ? createdAtValue.toISOString() : new Date(createdAtValue).toISOString(),
      },
    },
    { status: 201 }
  );
}

export async function DELETE(request: NextRequest) {
  const user = await getCurrentUserFromHeaders(request.headers);

  if (!user) {
    return UNAUTHORIZED_RESPONSE;
  }

  const body = (await request.json().catch(() => ({}))) as WatchlistPayload;
  const symbol = body.symbol?.trim().toUpperCase();

  if (!symbol) {
    return NextResponse.json({ success: false, error: 'Symbol is required' }, { status: 400 });
  }

  await connectToDatabase();

  await Watchlist.findOneAndDelete({ userId: user.id, symbol });

  return NextResponse.json({ success: true });
}
