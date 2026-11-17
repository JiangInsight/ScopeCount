#pragma once
#include "prefix_policy.hpp"
namespace prefix_admission {
inline FixedPlan jointProfile(const Tree& tree,const vector<Q>& rules){
    if(rules.empty()||rules.size()>64)throw invalid_argument("online compiler requires 1 to 64 checks");
    FixedPlan profile;profile.b=int(rules.size());map<int,pair<U,U>> combined;
    for(size_t off=0;off<rules.size();off+=8){
        vector<Q> batch(rules.begin()+off,rules.begin()+min(rules.size(),off+8));
        for(auto term:frontier(tree,batch,false)){
            combined[term.x].first|=U(term.plus)<<off;
            combined[term.x].second|=U(term.minus)<<off;
        }
    }
    for(auto [node,signs]:combined)profile.terms.push_back({node,signs.first,signs.second});
    admission::price_terms(tree,rules,profile);return profile;
}
struct OnlineStats{
    U compile_ns=0,kernel_ns=0,plan_hits=0,predicate_hits=0,new_predicates=0,terms=0;
    U bitmap_bytes=0,term_bytes=0;
};
class OnlineExecution{
    History policy;
    map<vector<Key>,FixedPlan> compiled;
    map<Key,Node> privateBitmaps;
    vector<bool> acquired;
    U bitmapBytes=0,termBytes=0;
    static I readNode(const Node& node,Range z,I rows){
        if(z.l==0&&z.r==rows)return node.w.empty()?I(node.p.size()):node.pref.back();
        return node.count(z);
    }
public:
    vector<I> evaluate(const Tree& tree,Columns& columns,Range z,const vector<Key>& rules,OnlineStats& stats){
        auto prepare=Clock::now();
        auto [it,fresh]=compiled.try_emplace(rules);
        if(fresh){
            vector<Q> q;for(auto [one,zero]:rules)q.push_back({"",one,zero,{}});
            it->second=jointProfile(tree,q);termBytes+=it->second.terms.capacity()*sizeof(admission::SharedNode);
        }else stats.plan_hits++;
        const FixedPlan &plan=it->second;
        size_t current=policy.observe(rules,plan);
        auto decision=policy.solve(current);
        for(size_t k=0;k<decision.bought.size();k++){
            if(k<acquired.size()&&acquired[k]&&!decision.bought[k])throw logic_error("nonmonotone placement");
            if(!decision.bought[k]||(k<acquired.size()&&acquired[k]))continue;
            auto key=policy.keys()[k];U fields=key.first|key.second;
            if((key.first&key.second)||popcount(fields)<=1)continue;
            auto &node=privateBitmaps[key];node=columns.cache({"",key.first,key.second,{}});
            bitmapBytes+=node.w.capacity()*sizeof(U)+node.pref.capacity()*sizeof(I);stats.new_predicates++;
        }
        acquired=move(decision.bought);stats.compile_ns=elapsed(prepare);
        stats.bitmap_bytes=bitmapBytes;stats.term_bytes=termBytes;
        auto start=Clock::now();vector<int64_t> acc(rules.size(),0);
        for(auto term:plan.terms){
            U plus=term.plus&decision.keep, minus=term.minus&decision.keep;
            if(!(plus|minus))continue;
            auto count=term.node?readNode(tree.t[term.node],z,tree.n):z.r-z.l;
            if(term.node)stats.terms++;
            admission::each(plus,[&](int j){acc[j]+=count;});
            admission::each(minus,[&](int j){acc[j]-=count;});
        }
        vector<I> result(rules.size());
        for(size_t j=0;j<rules.size();j++){
            if((decision.keep>>j)&1){
                if(acc[j]<0||U(acc[j])>z.r-z.l)throw logic_error("invalid shared result");
                result[j]=I(acc[j]);continue;
            }
            auto key=rules[j];U fields=key.first|key.second;
            if(key.first&key.second)result[j]=0;
            else if(!fields)result[j]=z.r-z.l;
            else if(has_single_bit(fields)){
                int bit=countr_zero(fields);I hits=columns.rankcol(bit,z.r)-columns.rankcol(bit,z.l);
                result[j]=key.first?hits:z.r-z.l-hits;
            }else{
                result[j]=readNode(privateBitmaps.at(key),z,tree.n);
                stats.predicate_hits++;
            }
        }
        stats.kernel_ns=elapsed(start);return result;
    }
};
}
