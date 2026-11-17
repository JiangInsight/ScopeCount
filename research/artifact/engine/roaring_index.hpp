
#pragma once
#include "roaring.h"

namespace compressed {
namespace api = roaring::api;
namespace detail = roaring::internal;

struct FreeBitmap {
    void operator()(api::roaring_bitmap_t* p) const { api::roaring_bitmap_free(p); }
};
using Bitmap = std::unique_ptr<api::roaring_bitmap_t, FreeBitmap>;
using Key = std::pair<U,U>;

struct Counter {
    Bitmap bitmap;
    U cardinality = 0;
    U payload_size = 0;

    void finish() {
        api::roaring_bitmap_run_optimize(bitmap.get());
        api::roaring_bitmap_shrink_to_fit(bitmap.get());
        cardinality = api::roaring_bitmap_get_cardinality(bitmap.get());


        const auto& directory=bitmap->high_low_container;
        payload_size=sizeof(*bitmap)+U(directory.allocation_size)*(sizeof(void*)+sizeof(uint16_t)+sizeof(uint8_t));
        for (int i=0;i<directory.size;i++) {
            auto container=directory.containers[i];
            switch (directory.typecodes[i]) {
                case ARRAY_CONTAINER_TYPE: {
                    auto v=static_cast<const detail::array_container_t*>(container);
                    payload_size+=sizeof(*v)+U(v->capacity)*sizeof(uint16_t);
                    break;
                }
                case BITSET_CONTAINER_TYPE:
                    payload_size+=sizeof(detail::bitset_container_t)+8192;
                    break;
                case RUN_CONTAINER_TYPE: {
                    auto v=static_cast<const detail::run_container_t*>(container);
                    payload_size+=sizeof(*v)+U(v->capacity)*sizeof(detail::rle16_t);
                    break;
                }
                default: throw std::logic_error("unexpected CRoaring container type");
            }
        }
    }

    I count(Range slice, I rows) const {
        if (slice.l == 0 && slice.r == rows) return I(cardinality);
        return I(api::roaring_bitmap_range_cardinality(bitmap.get(),slice.l,slice.r));
    }
};

class Index {
    std::array<Counter,64> columns;
    Counter empty;
    std::map<Key,Counter> cached;
    I n;
    const Counter& column(unsigned j) const { return columns[j].bitmap ? columns[j] : empty; }



    static Counter from_words(const std::vector<U>& words) {
        const size_t block_words=1024;
        Counter result;
        result.bitmap.reset(api::roaring_bitmap_create_with_capacity(uint32_t((words.size()+1023)/1024)));
        if (!result.bitmap) throw std::bad_alloc();
        for (size_t offset=0; offset<words.size(); offset+=block_words) {
            size_t len=std::min(block_words,words.size()-offset);
            int cardinality=0;
            for (size_t j=0;j<len;j++) cardinality+=std::popcount(words[offset+j]);
            if (!cardinality) continue;
            auto bits=detail::bitset_container_create();
            if (!bits) throw std::bad_alloc();
            std::memcpy(bits->words,words.data()+offset,len*sizeof(U));
            bits->cardinality=cardinality;
            uint16_t key=uint16_t(offset/block_words);
            if (cardinality<=4096) {
                auto sparse=detail::array_container_from_bitset(bits);
                detail::bitset_container_free(bits);
                if (!sparse) throw std::bad_alloc();
                detail::ra_append(&result.bitmap->high_low_container,key,sparse,ARRAY_CONTAINER_TYPE);
            } else {
                detail::ra_append(&result.bitmap->high_low_container,key,bits,BITSET_CONTAINER_TYPE);
            }
        }
        result.finish();
        return result;
    }

    Counter compile(Key key) const {
        std::vector<unsigned> order;
        for (U fields=key.first|key.second; fields; fields&=fields-1) order.push_back(std::countr_zero(fields));
        auto selectivity = [&](unsigned col) {
            auto card=column(col).cardinality;
            return (key.first>>col)&1 ? card : n-card;
        };
        std::sort(order.begin(),order.end(),[&](unsigned a,unsigned b){return selectivity(a)<selectivity(b);});
        unsigned first=order.front();
        auto initial=column(first).bitmap.get();
        Counter result;
        result.bitmap.reset((key.first>>first)&1 ? api::roaring_bitmap_copy(initial)
                                                 : api::roaring_bitmap_flip(initial,0,n));
        if (!result.bitmap) throw std::bad_alloc();
        for (size_t i=1;i<order.size() && !api::roaring_bitmap_is_empty(result.bitmap.get());i++) {
            unsigned col=order[i];
            auto input=column(col).bitmap.get();
            if ((key.first>>col)&1) api::roaring_bitmap_and_inplace(result.bitmap.get(),input);
            else api::roaring_bitmap_andnot_inplace(result.bitmap.get(),input);
        }
        result.finish();
        return result;
    }

public:
    U base_bytes=0,cache_bytes=0;
    Index(I nrows,const std::vector<U>&fields,const std::vector<std::vector<U>>&masks):n(nrows) {
        empty=from_words({});
        base_bytes=empty.payload_size;
        for (U field:fields) {
            columns[field]=from_words(masks[field]);
            base_bytes+=columns[field].payload_size;
        }
    }
    template<class Metrics> std::vector<I> count(Range slice,const std::vector<Key>&rules,Metrics& stats) {
        std::vector<I> result;
        result.reserve(rules.size());
        for (auto rule:rules) {
            auto start=Clock::now();
            U fields=rule.first|rule.second;
            I answer;
            if (rule.first&rule.second) answer=0;
            else if (!fields) answer=slice.r-slice.l;
            else if (std::has_single_bit(fields)) {
                I hits=column(std::countr_zero(fields)).count(slice,n);
                answer=rule.first ? hits : slice.r-slice.l-hits;
            } else {
                auto found=cached.find(rule);
                if (found==cached.end()) {
                    auto built=compile(rule);
                    cache_bytes+=built.payload_size;
                    found=cached.emplace(rule,std::move(built)).first;
                    stats.new_predicates++;
                } else stats.predicate_hits++;
                stats.compile_ns+=elapsed(start);
                start=Clock::now();
                answer=found->second.count(slice,n);
            }
            result.push_back(answer);
            stats.kernel_ns+=elapsed(start);
        }
        stats.cache_bytes=cache_bytes;
        return result;
    }
};
}
