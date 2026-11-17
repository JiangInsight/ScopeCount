
#include "../revision/online_engine.hpp"
#include <cstring>
#include <memory>
#include <mutex>
#include <sstream>
#include <tuple>
#ifdef SCOPECOUNT_ROARING
#include "roaring_index.hpp"
#endif
#define DUCKDB_EXTENSION_NAME scopecount
#include "duckdb_extension.h"
DUCKDB_EXTENSION_EXTERN

namespace audit {
using Rule = pair<U,U>;
using Rules = vector<Rule>;
struct Metrics {
    U compile_ns=0, kernel_ns=0, plan_hits=0, predicate_hits=0, new_predicates=0;
    U terms=0, base_bytes=0, cache_bytes=0;
};

struct Snapshot {
    string method;
    prefix_admission::OnlineExecution online;
    I rows;
    unique_ptr<Tree> tree;
    unique_ptr<Columns> columns;
#ifdef SCOPECOUNT_ROARING
    unique_ptr<compressed::Index> compressed;
#endif
    vector<U> raw;
    map<Rules,Plan> plans;
    map<Rule,Node> cache;
    map<U,vector<I>> postings;
    Metrics stats;
    U native_build_ns=0;
    bool profiling=false;
    vector<array<U,8>> history;

    Snapshot(string name,I n):method(move(name)),rows(n){}
    Snapshot(string name, vector<U> signatures):method(move(name)),rows(I(signatures.size())) {
        if(!rows)return;
        if(method=="tree" || method=="independent" || method=="online"){
            tree=make_unique<Tree>(signatures);
            stats.base_bytes=tree->t.capacity()*sizeof(Node);
            for(const auto &v:tree->t)
                stats.base_bytes+=4*v.p.capacity()+8*v.w.capacity()+4*v.pref.capacity();
        }
        if(method=="bitmap" || method=="words" || method=="online"){
            columns=make_unique<Columns>(signatures);
            for(size_t j=0;j<64;j++) stats.base_bytes+=8*columns->w[j].capacity()+4*columns->pref[j].capacity();
        }else if(method=="lazy"){
            raw=move(signatures);
            stats.base_bytes=raw.capacity()*sizeof(U);
        }else if(method=="leaf"){
            for(I i=0;i<rows;i++) postings[signatures[i]].push_back(i);
            for(const auto& kv:postings)stats.base_bytes+=sizeof(kv)+4*kv.second.capacity();
        }else if(!tree)throw invalid_argument("unknown snapshot backend: "+method);
    }
    bool matches(U s,Rule r) const {return (s&r.first)==r.first && !(s&r.second);}
    I rank_range(const Node& n,Range z)const{
        if(z.l==0 && z.r==rows)return n.w.empty()?I(n.p.size()):n.pref.back();
        return n.count(z);
    }
    Node from_rows(Rule r)const{
        Node n;n.w.assign((U(rows)+63)/64,0);
        for(I i=0;i<rows;i++)if(matches(raw[i],r))n.w[i/64]|=U(1)<<(i%64);
        n.pref.resize(n.w.size()+1);
        for(size_t i=0;i<n.w.size();i++)n.pref[i+1]=n.pref[i]+popcount(n.w[i]);
        return n;
    }
    I scan_words(Rule r,Range z)const{
        if(z.r==z.l)return 0;
        I total=0;
        for(size_t k=z.l/64;k<=(z.r-1)/64;k++){
            U v=~U(0);
            if(k==z.l/64)v&=~U(0)<<(z.l%64);
            if(k==(z.r-1)/64 && z.r%64)v&=(U(1)<<(z.r%64))-1;
            for(U active=r.first|r.second;active && v;active&=active-1){
                unsigned j=countr_zero(active);
                U word=columns->w[j].empty()?0:columns->w[j][k];
                v&=(r.first>>j&1)?word:~word;
            }
            total+=popcount(v);
        }
        return total;
    }
    vector<I> count(Range z,const Rules& rules){
        if(z.r>rows || z.l>z.r || rules.empty())throw invalid_argument("invalid slice or empty output");
        const U base=stats.base_bytes, cached=stats.cache_bytes;
        stats=Metrics{};stats.base_bytes=base;stats.cache_bytes=cached;
        vector<I> result(rules.size());
        if(!rows)return result;
#ifdef SCOPECOUNT_ROARING
        if(compressed)return compressed->count(z,rules,stats);
#endif
        if(method=="online"){
            prefix_admission::OnlineStats details;result=online.evaluate(*tree,*columns,z,rules,details);
            stats.compile_ns=details.compile_ns;stats.kernel_ns=details.kernel_ns;stats.terms=details.terms;
            stats.plan_hits=details.plan_hits;stats.predicate_hits=details.predicate_hits;stats.new_predicates=details.new_predicates;
            stats.cache_bytes=details.bitmap_bytes+details.term_bytes;return result;
        }
        if(tree){
            for(size_t off=0;off<rules.size();off+=8){
                const size_t end=min(rules.size(),off+8);
                auto start=Clock::now();Rules key(rules.begin()+off,rules.begin()+end);
                auto [it,fresh]=plans.try_emplace(key);
                if(fresh){
                    vector<Q> q;for(auto [one,zero]:key)q.push_back({"",one,zero,{}});
                    it->second=frontier(*tree,q,method=="independent");
                    stats.cache_bytes+=it->second.capacity()*sizeof(Term)+it->first.capacity()*sizeof(Rule);
                }else stats.plan_hits++;
                stats.compile_ns+=elapsed(start);start=Clock::now();
                Ans answers{};
                for(const auto &term:it->second){
                    const int64_t n=term.x?rank_range(tree->t[term.x],z):z.r-z.l;
                    stats.terms+=term.x!=0;
                    for(unsigned m=term.plus;m;m&=m-1)answers[countr_zero(m)]+=n;
                    for(unsigned m=term.minus;m;m&=m-1)answers[countr_zero(m)]-=n;
                }
                for(size_t j=0;j<key.size();j++){
                    if(answers[j]<0 || U(answers[j])>z.r-z.l)throw logic_error("invalid signed output");
                    result[off+j]=I(answers[j]);
                }
                stats.kernel_ns+=elapsed(start);
            }
        }else if(method=="leaf"){
            auto start=Clock::now();
            for(const auto& [s,p]:postings){
                I n=(z.l==0 && z.r==rows)?I(p.size()):I(lower_bound(p.begin(),p.end(),z.r)-lower_bound(p.begin(),p.end(),z.l));
                for(size_t j=0;j<rules.size();j++)if(matches(s,rules[j]))result[j]+=n;
            }
            stats.kernel_ns=elapsed(start);
        }else{
            for(size_t j=0;j<rules.size();j++){
                auto [one,zero]=rules[j];const U fields=one|zero;
                auto start=Clock::now();
                if(one&zero){result[j]=0;}
                else if(!fields){result[j]=z.r-z.l;}
                else if(columns && has_single_bit(fields)){
                    int col=countr_zero(fields);I hits=columns->rankcol(col,z.r)-columns->rankcol(col,z.l);
                    result[j]=one?hits:z.r-z.l-hits;
                }else if(method=="words"){result[j]=scan_words(rules[j],z);}
                else{
                    auto [it,fresh]=cache.try_emplace(rules[j]);
                    if(fresh){
                        it->second=columns?columns->cache({"",one,zero,{}}):from_rows(rules[j]);
                        stats.cache_bytes+=8*it->second.w.capacity()+4*it->second.pref.capacity();stats.new_predicates++;
                    }else stats.predicate_hits++;
                    stats.compile_ns+=elapsed(start);start=Clock::now();
                    result[j]=rank_range(it->second,z);
                }
                stats.kernel_ns+=elapsed(start);
            }
        }
        return result;
    }
};

struct Registry{mutex lock;U next=1;map<U,unique_ptr<Snapshot>> state;};
using Shared=shared_ptr<Registry>;
Registry& registry(duckdb_function_info info){return **static_cast<Shared*>(duckdb_scalar_function_get_extra_info(info));}
void destroy_shared(void* p){delete static_cast<Shared*>(p);}
void valid(duckdb_vector vec,idx_t i){
    auto* mask=duckdb_vector_get_validity(vec);
    if(mask && !duckdb_validity_row_is_valid(mask,i))throw invalid_argument("NULL list element");
}
vector<U> unpack(duckdb_vector v,idx_t row){
    valid(v,row);
    auto e=static_cast<duckdb_list_entry*>(duckdb_vector_get_data(v))[row];
    if(e.length>=UINT32_MAX)throw length_error("snapshot or bundle exceeds 32-bit row range");
    auto child=duckdb_list_vector_get_child(v);
    auto* values=static_cast<U*>(duckdb_vector_get_data(child));
    if(duckdb_vector_get_validity(child))for(idx_t j=0;j<e.length;j++)valid(child,e.offset+j);
    if(!e.length)return {};
    return {values+e.offset,values+e.offset+e.length};
}
template<class T> T scalar(duckdb_data_chunk args,idx_t col,idx_t row){
    auto v=duckdb_data_chunk_get_vector(args,col);valid(v,row);return static_cast<T*>(duckdb_vector_get_data(v))[row];
}
void emit(duckdb_vector out,idx_t i,const vector<U>&values,idx_t &offset){
    if(duckdb_list_vector_reserve(out,offset+values.size())!=DuckDBSuccess)throw bad_alloc();
    if(duckdb_list_vector_set_size(out,offset+values.size())!=DuckDBSuccess)throw bad_alloc();
    auto child=duckdb_list_vector_get_child(out);
    copy(values.begin(),values.end(),static_cast<U*>(duckdb_vector_get_data(child))+offset);
    static_cast<duckdb_list_entry*>(duckdb_vector_get_data(out))[i]={offset,values.size()};offset+=values.size();
}
void build(duckdb_function_info info,duckdb_data_chunk args,duckdb_vector out){
    try{
        auto &reg=registry(info);lock_guard guard(reg.lock);
        for(idx_t i=0;i<duckdb_data_chunk_get_size(args);i++){
            auto name=scalar<duckdb_string_t>(args,0,i);
            string method(duckdb_string_t_data(&name),duckdb_string_t_length(name));
            auto r=unpack(duckdb_data_chunk_get_vector(args,1),i);

            auto start=Clock::now();auto state=make_unique<Snapshot>(method,move(r));state->native_build_ns=elapsed(start);
            U id=reg.next++;reg.state.emplace(id,move(state));
            static_cast<U*>(duckdb_vector_get_data(out))[i]=id;
        }
    }catch(const exception&e){duckdb_scalar_function_set_error(info,e.what());}
}
void query(duckdb_function_info info,duckdb_data_chunk args,duckdb_vector out){
    try{
        auto &reg=registry(info);lock_guard guard(reg.lock);idx_t offset=0;
        for(idx_t i=0;i<duckdb_data_chunk_get_size(args);i++){
            auto &state=*reg.state.at(scalar<U>(args,0,i));
            Range z{scalar<I>(args,1,i),scalar<I>(args,2,i)};
            auto a=unpack(duckdb_data_chunk_get_vector(args,3),i),b=unpack(duckdb_data_chunk_get_vector(args,4),i);
            if(a.size()!=b.size())throw invalid_argument("predicate lists have different lengths");
            Rules rules;for(size_t j=0;j<a.size();j++)rules.emplace_back(a[j],b[j]);
            auto values=state.count(z,rules);emit(out,i,{values.begin(),values.end()},offset);
            if(state.profiling){const auto &s=state.stats;state.history.push_back({s.compile_ns,s.kernel_ns,s.plan_hits,s.predicate_hits,s.new_predicates,s.terms,s.base_bytes,s.cache_bytes});}
        }
    }catch(const exception&e){duckdb_scalar_function_set_error(info,e.what());}
}
void metrics(duckdb_function_info info,duckdb_data_chunk args,duckdb_vector out){
    try{
        auto &reg=registry(info);lock_guard guard(reg.lock);idx_t off=0;
        for(idx_t i=0;i<duckdb_data_chunk_get_size(args);i++){
            auto &state=*reg.state.at(scalar<U>(args,0,i));auto s=state.stats;emit(out,i,{s.compile_ns,s.kernel_ns,s.plan_hits,s.predicate_hits,s.new_predicates,s.terms,s.base_bytes,s.cache_bytes,state.native_build_ns},off);
        }
    }catch(const exception&e){duckdb_scalar_function_set_error(info,e.what());}
}
void profile(duckdb_function_info info,duckdb_data_chunk args,duckdb_vector out){
    try{auto&reg=registry(info);lock_guard guard(reg.lock);
        for(idx_t i=0;i<duckdb_data_chunk_get_size(args);i++){
            auto &s=*reg.state.at(scalar<U>(args,0,i));s.profiling=true;s.history.clear();static_cast<U*>(duckdb_vector_get_data(out))[i]=1;
        }
    }catch(const exception&e){duckdb_scalar_function_set_error(info,e.what());}
}
void history(duckdb_function_info info,duckdb_data_chunk args,duckdb_vector out){
    try{auto&reg=registry(info);lock_guard guard(reg.lock);idx_t offset=0;
        for(idx_t i=0;i<duckdb_data_chunk_get_size(args);i++){
            auto &s=*reg.state.at(scalar<U>(args,0,i));vector<U>flat;
            flat.reserve(s.history.size()*8);for(const auto&row:s.history)flat.insert(flat.end(),row.begin(),row.end());
            emit(out,i,flat,offset);
        }
    }catch(const exception&e){duckdb_scalar_function_set_error(info,e.what());}
}
void drop(duckdb_function_info info,duckdb_data_chunk args,duckdb_vector out){
    try{
        auto &reg=registry(info);lock_guard guard(reg.lock);
        for(idx_t i=0;i<duckdb_data_chunk_get_size(args);i++)
            static_cast<U*>(duckdb_vector_get_data(out))[i]=reg.state.erase(scalar<U>(args,0,i));
    }catch(const exception&e){duckdb_scalar_function_set_error(info,e.what());}
}
void add(duckdb_connection con, const Shared&reg,const char *name,initializer_list<duckdb_logical_type>params,
         duckdb_logical_type result,duckdb_scalar_function_t callback){
    auto fn=duckdb_create_scalar_function();duckdb_scalar_function_set_name(fn,name);
    for(auto p:params)duckdb_scalar_function_add_parameter(fn,p);
    duckdb_scalar_function_set_return_type(fn,result);duckdb_scalar_function_set_function(fn,callback);
    duckdb_scalar_function_set_volatile(fn);duckdb_scalar_function_set_extra_info(fn,new Shared(reg),destroy_shared);
    auto ok=duckdb_register_scalar_function(con,fn);duckdb_destroy_scalar_function(&fn);
    if(ok!=DuckDBSuccess)throw runtime_error(string("registration failed: ")+name);
}

#include "direct_bitmap.hpp"
}
DUCKDB_EXTENSION_ENTRYPOINT(duckdb_connection con,duckdb_extension_info info,struct duckdb_extension_access *access){
    auto u=duckdb_create_logical_type(DUCKDB_TYPE_UBIGINT),i=duckdb_create_logical_type(DUCKDB_TYPE_UINTEGER);
    auto str=duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR),list=duckdb_create_list_type(u);
    auto blob=duckdb_create_logical_type(DUCKDB_TYPE_BLOB), blobs=duckdb_create_list_type(blob);
    auto state=make_shared<audit::Registry>();bool ok=true;
    try{
        audit::register_validity(con);audit::add(con,state,"scope_attach",{str,i,list,blobs},u,audit::attach);
        audit::add(con,state,"scope_build",{str,list},u,audit::build);
        audit::add(con,state,"scope_count",{u,i,i,list,list},list,audit::query);
        audit::add(con,state,"scope_stats",{u},list,audit::metrics);
        audit::add(con,state,"scope_profile",{u},u,audit::profile);
        audit::add(con,state,"scope_history",{u},list,audit::history);
        audit::add(con,state,"scope_drop",{u},u,audit::drop);
    }catch(const exception&e){access->set_error(info,e.what());ok=false;}
    for(auto *p:{&u,&i,&str,&list,&blob,&blobs})duckdb_destroy_logical_type(p);return ok;
}
